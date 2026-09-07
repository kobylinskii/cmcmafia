"""Прогон диалогов бота без Telegram и без сети.

Роутеры, фильтры и состояния собираются ровно так же, как в проде
(`setup_routers`), но Bot подменён заглушкой, которая записывает исходящие
вызовы API вместо походов в сеть, а ApiClient -- маленьким фейком поверх
словаря. Это ловит то, что молча ломается при перекладывании обработчиков:
не сработавший фильтр, состояние, из которого нет выхода, кнопку с
callback_data, которую никто не слушает.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageText,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    Contact,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    Update,
    User,
)

from app.api_client import LOCAL_TZ

USER_ID = 424242
CHAT_ID = 424242

# Те же поля, что и в profile_change_service.MODERATED_FIELDS на бэкенде.
MODERATED_FIELDS = ("full_name", "nickname", "age", "experience", "bio")


class MockedBot(Bot):
    """Bot, который никуда не ходит: запоминает вызовы и отдаёт правдоподобные
    ответы. Нужен только для того, чтобы Dispatcher отработал целиком."""

    def __init__(self) -> None:
        super().__init__(token="42:TEST")
        self.calls: list[TelegramMethod] = []
        self._next_message_id = 1000

    async def __call__(self, method: TelegramMethod, request_timeout: int | None = None) -> Any:
        self.calls.append(method)
        if isinstance(method, SendMessage):
            self._next_message_id += 1
            return Message(
                message_id=self._next_message_id,
                date=datetime.now(),
                chat=Chat(id=CHAT_ID, type="private"),
                text=method.text,
            )
        if isinstance(method, EditMessageText):
            return Message(
                message_id=method.message_id or 0,
                date=datetime.now(),
                chat=Chat(id=CHAT_ID, type="private"),
                text=method.text,
            )
        if isinstance(method, (DeleteMessage, AnswerCallbackQuery)):
            return True
        return True

    # ---- удобные срезы записанного
    @property
    def texts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, (SendMessage, EditMessageText))]

    @property
    def last_text(self) -> str:
        return self.texts[-1]

    def last_inline(self) -> list[str]:
        for call in reversed(self.calls):
            markup = getattr(call, "reply_markup", None)
            if isinstance(markup, InlineKeyboardMarkup):
                return [b.callback_data for row in markup.inline_keyboard for b in row]
        return []

    def last_reply_buttons(self) -> list[str]:
        for call in reversed(self.calls):
            markup = getattr(call, "reply_markup", None)
            if isinstance(markup, ReplyKeyboardMarkup):
                return [b.text for row in markup.keyboard for b in row]
        return []

    def reset(self) -> None:
        self.calls.clear()


def _session(session_id: int, starts_at: datetime, **overrides: Any) -> dict:
    session = {
        "id": session_id,
        "starts_at": starts_at.isoformat(),
        "location": "ВМК МГУ",
        "game_type": "funky",
        "status": "scheduled",
        "registration_until": None,
        "is_open": True,
        "hosts": 0,
        "judges": 0,
        "players": 3,
        "max_players": 10,
        "reserves": 0,
    }
    session.update(overrides)
    return session


class FakeApi:
    """Столько API, сколько нужно диалогам: профиль, статистика и расписание."""

    def __init__(self) -> None:
        self.profile: dict | None = None
        self.registered: list[tuple[int, str]] = []
        self.reserve_next = False
        # Кого бэкенд поднял из резерва этой записью. Не None только тогда,
        # когда запись в штаб освободила место за столом.
        self.promote_on_register: int | None = None
        self.broadcast_recipients: list[int] = []
        self.broadcast_audience: list[int] = []
        soon = datetime.now(LOCAL_TZ) + timedelta(days=1)
        self.session = _session(7, soon.replace(hour=18, minute=0, second=0, microsecond=0))

    @property
    def sessions(self) -> dict[int, dict]:
        return {self.session["id"]: self.session}

    @property
    def _day(self) -> str:
        return datetime.fromisoformat(self.session["starts_at"]).strftime("%d.%m.%Y")

    async def get_profile(self, tg_id: int, telegram_username: str | None = None) -> dict | None:
        return self.profile

    async def register_player(self, **fields: Any) -> dict:
        self.profile = {
            "telegram_id": fields["telegram_id"],
            "nickname": fields["nickname"],
            "slug": "player",
            "salutation": fields["salutation"],
            "full_name": fields["full_name"],
            "affiliation": fields["affiliation"],
            "phone": fields["phone"],
            "can_play": fields["can_play"],
            "can_staff": fields["can_staff"],
            "is_bot_admin": False,
            "age": None,
            "favorite_role": None,
            "experience": None,
            "bio": None,
            "confirmation_status": "pending",
            "rejection_reason": None,
            "pending_changes": {},
        }
        return self.profile

    async def update_profile(self, tg_id: int, **fields: Any) -> dict:
        """Повторяет правило бэкенда: у подтверждённого игрока текстовые поля
        уходят на проверку, кнопочные применяются сразу."""
        for field, value in fields.items():
            if field in MODERATED_FIELDS and self.profile["confirmation_status"] == "confirmed":
                self.profile["pending_changes"][field] = value
                continue
            self.profile[field] = value
        return self.profile

    async def my_stats(self, tg_id: int) -> dict:
        return {"total_games": 0, "wins": 0, "win_rate": None, "rating": None,
                "rating_games_count": 0, "rank": None}

    async def list_game_days(self, tg_id: int, game_type: str | None = None) -> list[str]:
        return [self._day]

    async def list_open_sessions(self, tg_id: int, game_type=None, day=None) -> list[dict]:
        return [self.session]

    async def get_session(self, tg_id: int, session_id: int) -> dict | None:
        return self.sessions.get(session_id)

    async def register_for_session(self, tg_id: int, session_id: int, role_kind: str) -> dict:
        if self.reserve_next:
            self.registered.append((session_id, "reserve"))
            return {
                "ok": True,
                "message": "Основной состав уже собран — вы в резерве, №2",
                "role": "reserve",
                "is_reserve": True,
                "reserve_position": 2,
            }
        self.registered.append((session_id, role_kind))
        return {
            "ok": True,
            "message": "Вы успешно записаны",
            "reason": None,
            "role": "host" if role_kind == "staff" else role_kind,
            "is_reserve": False,
            "promoted_telegram_id": self.promote_on_register,
            "promoted_nickname": "Резервист" if self.promote_on_register else None,
        }

    async def my_registrations(self, tg_id: int) -> list[dict]:
        return [
            {
                "game_id": session_id,
                "starts_at": self.session["starts_at"],
                "location": self.session["location"],
                "game_type": self.session["game_type"],
                "role": role,
                "is_reserve": False,
            }
            for session_id, role in self.registered
        ]

    async def session_roster(self, tg_id: int, session_id: int) -> dict:
        return {"registrations": [{"nickname": "Шериф", "role": "player", "telegram_id": 1,
                                   "telegram_username": None}], "reserves": []}

    async def cancel_registration(self, tg_id: int, session_id: int) -> dict:
        self.registered = [item for item in self.registered if item[0] != session_id]
        return {"ok": True, "message": "Запись отменена", "promoted_telegram_id": None}

    # ---- админские ручки
    async def admin_weekly_broadcast(self, tg_id: int, days: int = 7) -> dict:
        return {
            "days": days,
            "games": [self.session],
            "recipients": [{"telegram_id": tg, "nickname": f"И{tg}"} for tg in self.broadcast_recipients],
        }

    async def admin_broadcast_audience(self, tg_id: int) -> dict:
        """Аудитория произвольного сообщения шире, чем у анонса: записавшихся
        она не вычитает."""
        return {
            "recipients": [
                {"telegram_id": tg, "nickname": f"И{tg}"} for tg in self.broadcast_audience
            ]
        }


def _fresh_routers():
    """Роутеры aiogram -- модульные синглтоны, и включить один и тот же роутер
    во второй Dispatcher нельзя (RuntimeError «already attached»). Каждому
    тесту нужен свой Dispatcher с чистым состоянием, поэтому модули
    обработчиков перезагружаются -- это честнее, чем отвязывать роутеры,
    трогая приватные поля aiogram."""
    import app.handlers as handlers_pkg
    from app.handlers import admin, common, profile, registration, schedule

    for module in (common, registration, profile, schedule, admin):
        importlib.reload(module)
    return importlib.reload(handlers_pkg).setup_routers


@pytest.fixture
def stack():
    bot = MockedBot()
    api = FakeApi()
    dp = Dispatcher(storage=MemoryStorage())
    dp["api"] = api
    _fresh_routers()(dp)
    return dp, bot, api


_update_id = [0]


def _message(text: str | None = None, contact: Contact | None = None) -> Update:
    _update_id[0] += 1
    return Update(
        update_id=_update_id[0],
        message=Message(
            message_id=_update_id[0],
            date=datetime.now(),
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=User(id=USER_ID, is_bot=False, first_name="Тест"),
            text=text,
            contact=contact,
        ),
    )


def _callback(data: str) -> Update:
    _update_id[0] += 1
    return Update(
        update_id=_update_id[0],
        callback_query=CallbackQuery(
            id=str(_update_id[0]),
            from_user=User(id=USER_ID, is_bot=False, first_name="Тест"),
            chat_instance="ci",
            data=data,
            message=Message(
                message_id=999,
                date=datetime.now(),
                chat=Chat(id=CHAT_ID, type="private"),
                from_user=User(id=1, is_bot=True, first_name="Бот"),
                text="экран",
            ),
        ),
    )


async def _register(dp: Dispatcher, bot: MockedBot) -> None:
    await dp.feed_update(bot, _message("/start"))
    await dp.feed_update(bot, _message(contact=Contact(phone_number="+79000000000", first_name="Тест", user_id=USER_ID)))
    await dp.feed_update(bot, _callback("nr:salutation:господин"))
    await dp.feed_update(bot, _message("Иванов Иван Иванович"))
    await dp.feed_update(bot, _callback("nr:affiliation:outside_need_pass"))
    await dp.feed_update(bot, _callback("nr:toggle:player"))
    await dp.feed_update(bot, _callback("nr:save"))
    await dp.feed_update(bot, _message("Шериф"))


@pytest.mark.asyncio
async def test_registration_walks_all_six_steps(stack):
    dp, bot, api = stack

    await dp.feed_update(bot, _message("/start"))
    assert "поделитесь номером телефона" in bot.last_text
    assert bot.last_reply_buttons() == ["📱 Поделиться номером телефона"]

    await dp.feed_update(bot, _message(contact=Contact(phone_number="+79000000000", first_name="Тест", user_id=USER_ID)))
    assert "Шаг 2 из 6" in bot.last_text
    assert bot.last_inline() == ["nr:salutation:господин", "nr:salutation:госпожа"]

    await dp.feed_update(bot, _callback("nr:salutation:господин"))
    assert "Шаг 3 из 6" in bot.last_text

    # Кривое ФИО не двигает шаг вперёд.
    await dp.feed_update(bot, _message("Иванов"))
    assert "ровно из трёх слов" in bot.last_text

    await dp.feed_update(bot, _message("Иванов Иван Иванович"))
    assert "Шаг 4 из 6" in bot.last_text

    await dp.feed_update(bot, _callback("nr:affiliation:outside_need_pass"))
    assert "Шаг 5 из 6" in bot.last_text

    await dp.feed_update(bot, _callback("nr:toggle:player"))
    await dp.feed_update(bot, _callback("nr:save"))
    assert "Шаг 6 из 6" in bot.last_text

    await dp.feed_update(bot, _message("Шериф"))
    assert "Готово, Шериф!" in bot.last_text
    assert "на проверку" in bot.last_text
    assert api.profile["confirmation_status"] == "pending"
    # Меню инлайновое: нижней клавиатуры после регистрации не остаётся, иначе
    # каждое её нажатие снова засоряло бы чат текстом.
    assert bot.last_inline() == ["sg:types", "mr:list:active", "pf:menu"]


@pytest.mark.asyncio
async def test_registration_refuses_to_finish_without_a_role(stack):
    dp, bot, _ = stack
    await dp.feed_update(bot, _message("/start"))
    await dp.feed_update(bot, _message(contact=Contact(phone_number="+79000000000", first_name="Т", user_id=USER_ID)))
    await dp.feed_update(bot, _callback("nr:salutation:господин"))
    await dp.feed_update(bot, _message("Иванов Иван Иванович"))
    await dp.feed_update(bot, _callback("nr:affiliation:vmk"))

    bot.reset()
    await dp.feed_update(bot, _callback("nr:save"))
    alerts = [c for c in bot.calls if isinstance(c, AnswerCallbackQuery) and c.show_alert]
    assert alerts and "хотя бы один" in alerts[0].text
    assert not bot.texts  # экран остался прежним, шага вперёд не было


@pytest.mark.asyncio
async def test_flow_screens_never_pile_up(stack):
    """Каждое нажатие инлайн-кнопки правит тот же экран, а не шлёт новый."""
    dp, bot, _ = stack
    await _register(dp, bot)

    for data in ("sg:types", "sg:type:funky", "sg:types", "mn:menu"):
        bot.reset()
        await dp.feed_update(bot, _callback(data))
        assert sum(isinstance(c, SendMessage) for c in bot.calls) == 0, data
        assert sum(isinstance(c, EditMessageText) for c in bot.calls) == 1, data


@pytest.mark.asyncio
async def test_typed_messages_are_removed_from_the_chat(stack):
    """Всё, что человек набрал руками, бот убирает: именно из таких сообщений
    -- «Профиль», «06.09.2026», «15:00-17:00» -- и состояла история диалога."""
    dp, bot, _ = stack
    await _register(dp, bot)

    bot.reset()
    await dp.feed_update(bot, _message("/menu"))
    deleted = [c.message_id for c in bot.calls if isinstance(c, DeleteMessage)]
    assert deleted, "команда должна исчезать из чата"

    bot.reset()
    await dp.feed_update(bot, _message("привет"))
    assert [c for c in bot.calls if isinstance(c, DeleteMessage)]
    assert "Клуб спортивной мафии" in bot.last_text


@pytest.mark.asyncio
async def test_signing_up_for_a_game_and_cancelling(stack):
    dp, bot, api = stack
    await _register(dp, bot)

    await dp.feed_update(bot, _callback("sg:types"))
    assert "На какие игры" in bot.last_text

    # У игрока отмечена одна роль -- экран выбора роли пропускается.
    await dp.feed_update(bot, _callback("sg:type:funky"))
    assert "Выберите день" in bot.last_text
    day_token = api._day.replace(".", "")
    assert f"sg:day:funky:player:{day_token}" in bot.last_inline()

    await dp.feed_update(bot, _callback(f"sg:day:funky:player:{day_token}"))
    assert "sg:game:funky:player:7" in bot.last_inline()

    await dp.feed_update(bot, _callback("sg:game:funky:player:7"))
    assert api.registered == [(7, "player")]

    await dp.feed_update(bot, _callback("mr:list:active"))
    assert "Предстоящие игры" in bot.last_text
    assert "mr:view:7" in bot.last_inline()

    await dp.feed_update(bot, _callback("mr:view:7"))
    assert "Игра #7" in bot.last_text
    assert "mr:cancel:7" in bot.last_inline()

    await dp.feed_update(bot, _callback("mr:cancel:7"))
    assert api.registered == []
    assert "Вы пока никуда не записаны" in bot.last_text


@pytest.mark.asyncio
async def test_eleventh_player_goes_to_reserve_in_one_tap(stack):
    """Отдельного экрана «мест нет» больше нет: запись на собранный стол сразу
    ставит в очередь, и человек узнаёт об этом из ответа на то же нажатие."""
    dp, bot, api = stack
    await _register(dp, bot)
    api.reserve_next = True
    api.session.update(players=10, reserves=1)

    day_token = api._day.replace(".", "")
    await dp.feed_update(bot, _callback("sg:types"))
    await dp.feed_update(bot, _callback("sg:type:funky"))
    await dp.feed_update(bot, _callback(f"sg:day:funky:player:{day_token}"))
    # Заполненный стол виден до нажатия -- подписью на самой кнопке.
    assert any("в резерв" in b.text for c in bot.calls
               for markup in [getattr(c, "reply_markup", None)] if isinstance(markup, InlineKeyboardMarkup)
               for row in markup.inline_keyboard for b in row)

    bot.reset()
    await dp.feed_update(bot, _callback("sg:game:funky:player:7"))
    assert api.registered == [(7, "reserve")]
    alerts = [c.text for c in bot.calls if isinstance(c, AnswerCallbackQuery) and c.show_alert]
    assert alerts and "в резерве, №2" in alerts[0]
    assert "sg:reserve:7" not in bot.last_inline(), "второе нажатие больше не требуется"


@pytest.mark.asyncio
async def test_profile_shows_moderation_status_and_edits_a_field(stack):
    dp, bot, api = stack
    await _register(dp, bot)

    await dp.feed_update(bot, _message("/profile"))
    assert "👤 Профиль" in bot.last_text
    assert "На проверке" in bot.last_text
    assert "Иванов Иван Иванович" in bot.last_text
    assert "📊 Сыгранных игр пока нет." in bot.last_text
    # Пока заявка на проверке, повторная отправка не предлагается.
    assert "pf:resubmit" not in bot.last_inline()

    await dp.feed_update(bot, _callback("pf:edit"))
    assert "pf:field:age" in bot.last_inline()

    await dp.feed_update(bot, _callback("pf:field:age"))
    assert "Сколько вам лет?" in bot.last_text

    await dp.feed_update(bot, _message("не скажу"))
    assert "число от 5 до 100" in bot.last_text

    await dp.feed_update(bot, _message("25"))
    assert api.profile["age"] == 25
    assert "Сохранено ✅" in bot.last_text
    assert "Возраст: 25" in bot.last_text


@pytest.mark.asyncio
async def test_confirmed_player_edit_waits_for_the_admin(stack):
    """У подтверждённого игрока текстовое поле не меняется сразу: правка уходит
    админу, а в карточке остаётся прежнее значение с пометкой."""
    dp, bot, api = stack
    await _register(dp, bot)
    api.profile["confirmation_status"] = "confirmed"

    await dp.feed_update(bot, _callback("pf:edit"))
    await dp.feed_update(bot, _callback("pf:field:bio"))
    assert "вступит в силу после проверки" in bot.last_text

    await dp.feed_update(bot, _message("Играю с 2015 года"))
    assert api.profile["bio"] is None, "значение не должно примениться до решения"
    assert api.profile["pending_changes"] == {"bio": "Играю с 2015 года"}
    assert "Отправлено на проверку" in bot.last_text
    assert "⏳ на проверке: Играю с 2015 года" in bot.last_text
    assert "Сохранено ✅" not in bot.last_text


@pytest.mark.asyncio
async def test_rejected_player_is_offered_a_second_look(stack):
    dp, bot, api = stack
    await _register(dp, bot)
    api.profile["confirmation_status"] = "rejected"
    api.profile["rejection_reason"] = "ФИО не совпадает с документом"

    await dp.feed_update(bot, _message("/profile"))
    assert "Заявка отклонена" in bot.last_text
    assert "ФИО не совпадает с документом" in bot.last_text
    assert "pf:resubmit" in bot.last_inline()


@pytest.mark.asyncio
async def test_admin_menu_is_hidden_from_ordinary_players(stack):
    dp, bot, api = stack
    await _register(dp, bot)

    assert "am:menu" not in bot.last_inline()

    bot.reset()
    await dp.feed_update(bot, _message("/admin"))
    assert "нет прав администратора" in bot.last_text

    api.profile["is_bot_admin"] = True
    await dp.feed_update(bot, _message("/admin"))
    assert "Админ-меню" in bot.last_text
    # Планировщик уехал на сайт: в боте остались только права и две рассылки.
    assert set(bot.last_inline()) == {"am:admins", "am:cast", "am:say", "mn:menu"}


@pytest.mark.asyncio
async def test_old_scheduler_buttons_say_where_the_planner_went(stack):
    """У админов в чате висят экраны, созданные до переезда. Нажатие на такую
    кнопку раньше просто крутило часики -- теперь оно объясняет, куда идти."""
    dp, bot, api = stack
    await _register(dp, bot)
    api.profile["is_bot_admin"] = True

    await dp.feed_update(bot, _message("/admin"))
    for stale in ("am:create", "am:days", "am:toconfirm", "am:date:26082026", "am:played:8"):
        await dp.feed_update(bot, _callback(stale))
        assert "Расписание игр теперь ведётся на сайте" in bot.last_text
        assert set(bot.last_inline()) == {"am:admins", "am:cast", "am:say", "mn:menu"}


@pytest.mark.asyncio
async def test_free_text_broadcast_asks_for_confirmation_before_sending(stack):
    """Опечатку в сообщении всему клубу не отозвать, поэтому между вводом и
    отправкой стоит предпросмотр с числом получателей."""
    dp, bot, api = stack
    await _register(dp, bot)
    api.profile["is_bot_admin"] = True
    api.broadcast_audience = [111, 222, 333]

    await dp.feed_update(bot, _message("/admin"))
    await dp.feed_update(bot, _callback("am:say"))
    assert "Что разослать?" in bot.last_text

    await dp.feed_update(bot, _message("Сегодня играем в 685-й аудитории"))
    assert "Получателей: 3" in bot.last_text
    assert "Сегодня играем в 685-й аудитории" in bot.last_text
    assert set(bot.last_inline()) == {"am:saygo", "am:say", "am:menu"}

    bot.reset()
    await dp.feed_update(bot, _callback("am:saygo"))
    sent = [c for c in bot.calls if isinstance(c, SendMessage)]
    assert [c.chat_id for c in sent] == [111, 222, 333]
    assert all(c.text == "Сегодня играем в 685-й аудитории" for c in sent)
    # Под объявлением кнопки нет: это не анонс, записываться некуда.
    assert all(c.reply_markup is None for c in sent)
    assert "Доставлено: 3" in bot.last_text


@pytest.mark.asyncio
async def test_broadcast_text_is_forgotten_after_it_is_sent(stack):
    """Повторное «Разослать» из старого экрана не должно уйти клубу дважды."""
    dp, bot, api = stack
    await _register(dp, bot)
    api.profile["is_bot_admin"] = True
    api.broadcast_audience = [111]

    await dp.feed_update(bot, _callback("am:say"))
    await dp.feed_update(bot, _message("Перенос на час позже"))
    await dp.feed_update(bot, _callback("am:saygo"))

    bot.reset()
    await dp.feed_update(bot, _callback("am:saygo"))
    assert [c for c in bot.calls if isinstance(c, SendMessage)] == []
    assert "наберите его заново" in bot.last_text


@pytest.mark.asyncio
async def test_overlong_broadcast_is_rejected_before_the_first_message(stack):
    dp, bot, api = stack
    await _register(dp, bot)
    api.profile["is_bot_admin"] = True
    api.broadcast_audience = [111]

    await dp.feed_update(bot, _callback("am:say"))
    await dp.feed_update(bot, _message("я" * 5000))
    assert "Слишком длинно" in bot.last_text
    assert "am:saygo" not in bot.last_inline()


@pytest.mark.asyncio
async def test_weekly_announcement_goes_only_to_those_without_a_registration(stack):
    dp, bot, api = stack
    await _register(dp, bot)
    api.profile["is_bot_admin"] = True
    # Кого рассылать -- решает API: он же и вычёркивает уже записанных.
    api.broadcast_recipients = [111, 222]

    await dp.feed_update(bot, _message("/admin"))
    await dp.feed_update(bot, _callback("am:cast"))
    assert "Получателей: 2" in bot.last_text
    assert "🎲 Игры на ближайшие 7 дней" in bot.last_text
    assert "am:castgo" in bot.last_inline()

    bot.reset()
    await dp.feed_update(bot, _callback("am:castgo"))
    sent = [c for c in bot.calls if isinstance(c, SendMessage)]
    assert [c.chat_id for c in sent] == [111, 222]
    assert all("Игры на ближайшие 7 дней" in c.text for c in sent)
    # В каждом сообщении -- кнопка записи, ведущая в обычный экран выбора.
    assert all(c.reply_markup.inline_keyboard[0][0].callback_data == "sg:types" for c in sent)
    assert "Доставлено: 2" in bot.last_text


@pytest.mark.asyncio
async def test_switching_to_staff_notifies_the_promoted_player(stack):
    """Уход из-за стола в штаб освобождает место, и поднятому из резерва
    приходит то же сообщение, что и при отмене чужой записи.

    Раньше промоушен был только у отмены: запись в штаб оставляла стол
    неполным при непустой очереди, и писать было некому.
    """
    dp, bot, api = stack
    await _register(dp, bot)
    api.promote_on_register = 555001

    day_token = api._day.replace(".", "")
    await dp.feed_update(bot, _callback("sg:types"))
    await dp.feed_update(bot, _callback("sg:type:funky"))
    await dp.feed_update(bot, _callback(f"sg:day:funky:staff:{day_token}"))

    bot.reset()
    await dp.feed_update(bot, _callback("sg:game:funky:staff:7"))
    assert api.registered == [(7, "staff")]

    promo = [
        call
        for call in bot.calls
        if isinstance(call, SendMessage) and call.chat_id == 555001
    ]
    assert promo, "поднятому из резерва никто не написал"
    assert "освободилось место" in promo[0].text
    assert "#7" in promo[0].text


@pytest.mark.asyncio
async def test_plain_registration_notifies_nobody(stack):
    """Обычная запись за стол ничьё место не освобождает -- лишних сообщений
    в чужие чаты быть не должно."""
    dp, bot, api = stack
    await _register(dp, bot)

    day_token = api._day.replace(".", "")
    await dp.feed_update(bot, _callback("sg:types"))
    await dp.feed_update(bot, _callback("sg:type:funky"))
    await dp.feed_update(bot, _callback(f"sg:day:funky:player:{day_token}"))

    bot.reset()
    await dp.feed_update(bot, _callback("sg:game:funky:player:7"))
    assert api.registered == [(7, "player")]
    assert not [
        call for call in bot.calls if isinstance(call, SendMessage) and call.chat_id != CHAT_ID
    ]
