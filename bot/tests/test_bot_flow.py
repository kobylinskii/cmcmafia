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
        self.played: list[int] = []
        self.deleted: list[int] = []
        self.created: list[dict] = []
        self.broadcast_recipients: list[int] = []
        soon = datetime.now(LOCAL_TZ) + timedelta(days=1)
        self.session = _session(7, soon.replace(hour=18, minute=0, second=0, microsecond=0))
        # Вчерашняя игра: её проведение админ ещё не подтверждал.
        past = datetime.now(LOCAL_TZ) - timedelta(days=1)
        self.past_session = _session(
            8, past.replace(hour=18, minute=0, second=0, microsecond=0), is_open=False, players=10
        )

    @property
    def sessions(self) -> dict[int, dict]:
        return {self.session["id"]: self.session, self.past_session["id"]: self.past_session}

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
            "role": role_kind,
            "is_reserve": False,
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
    async def admin_sessions_awaiting_confirmation(self, tg_id: int) -> list[dict]:
        return [self.past_session] if self.past_session["id"] not in self.played else []

    async def admin_mark_session_played(self, tg_id: int, session_id: int) -> dict:
        self.played.append(session_id)
        self.sessions[session_id]["status"] = "played"
        return self.sessions[session_id]

    async def admin_delete_session(self, tg_id: int, session_id: int) -> bool:
        self.deleted.append(session_id)
        return True

    async def admin_recent_locations(self, tg_id: int) -> list[str]:
        return ["ВМК МГУ, ауд. 685"]

    async def admin_check_conflicts(self, tg_id: int, starts: list[str]) -> list[str]:
        return []

    async def admin_create_sessions_bulk(
        self, tg_id: int, starts: list[str], location: str, game_type: str
    ) -> list[int]:
        self.created.append({"starts": starts, "location": location, "game_type": game_type})
        return list(range(100, 100 + len(starts)))

    async def admin_day_cards(self, tg_id: int) -> list[dict]:
        return [{"day": self._day, "types": ["funky"]}]

    async def admin_sessions_by_day(self, tg_id: int, day: str) -> list[dict]:
        return [self.session]

    async def admin_weekly_broadcast(self, tg_id: int, days: int = 7) -> dict:
        return {
            "days": days,
            "games": [self.session],
            "recipients": [{"telegram_id": tg, "nickname": f"И{tg}"} for tg in self.broadcast_recipients],
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
    assert "Добро пожаловать" in bot.last_text
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
    assert set(bot.last_inline()) == {
        "am:create", "am:days", "am:toconfirm", "am:cast", "am:admins", "mn:menu"
    }


@pytest.mark.asyncio
async def test_game_day_is_created_without_typing_a_single_date(stack):
    """День, часы и место выбираются кнопками. Руками админ набирал «06.09.2026»
    и «15:00-17:00», и каждая опечатка стоила ещё пары сообщений в чате."""
    dp, bot, api = stack
    await _register(dp, bot)
    api.profile["is_bot_admin"] = True

    await dp.feed_update(bot, _message("/admin"))
    await dp.feed_update(bot, _callback("am:create"))
    await dp.feed_update(bot, _callback("am:newtype:funky"))
    assert "Выберите день" in bot.last_text
    assert any(data.startswith("am:date:") for data in bot.last_inline())

    await dp.feed_update(bot, _callback("am:date:26082026"))
    assert "Во сколько начинается" in bot.last_text

    await dp.feed_update(bot, _callback("am:from:18"))
    assert "am:to:19" in bot.last_inline()
    assert "am:to:18" not in bot.last_inline(), "конец не может совпадать с началом"

    await dp.feed_update(bot, _callback("am:to:21"))
    assert "Где играем" in bot.last_text
    assert bot.last_inline()[:2] == ["am:loc:0", "am:locnew"]

    await dp.feed_update(bot, _callback("am:loc:0"))
    assert api.created == [
        {
            "starts": ["26.08.2026 18:00", "26.08.2026 19:00", "26.08.2026 20:00"],
            "location": "ВМК МГУ, ауд. 685",
            "game_type": "funky",
        }
    ]
    assert "Создано игр: 3" in bot.last_text


@pytest.mark.asyncio
async def test_past_game_reaches_review_only_after_the_admin_confirms_it(stack):
    dp, bot, api = stack
    await _register(dp, bot)
    api.profile["is_bot_admin"] = True

    await dp.feed_update(bot, _message("/admin"))
    assert "Подтвердить проведение (1)" in "".join(
        b.text for c in bot.calls
        for markup in [getattr(c, "reply_markup", None)] if isinstance(markup, InlineKeyboardMarkup)
        for row in markup.inline_keyboard for b in row
    )

    await dp.feed_update(bot, _callback("am:toconfirm"))
    assert "am:confirm:8" in bot.last_inline()

    await dp.feed_update(bot, _callback("am:confirm:8"))
    assert "подтвердите, состоялась ли она" in bot.last_text
    assert "am:played:8" in bot.last_inline()
    assert "am:notheld:8" in bot.last_inline()

    await dp.feed_update(bot, _callback("am:played:8"))
    assert api.played == [8]
    assert "Все прошедшие игры подтверждены" in bot.last_text


@pytest.mark.asyncio
async def test_game_that_did_not_happen_is_deleted_with_a_confirmation(stack):
    dp, bot, api = stack
    await _register(dp, bot)
    api.profile["is_bot_admin"] = True

    await dp.feed_update(bot, _message("/admin"))
    await dp.feed_update(bot, _callback("am:toconfirm"))
    await dp.feed_update(bot, _callback("am:confirm:8"))

    await dp.feed_update(bot, _callback("am:notheld:8"))
    assert "не состоялась?" in bot.last_text
    assert api.deleted == [], "удаление только после подтверждения"

    await dp.feed_update(bot, _callback("am:notheldok:8"))
    assert api.deleted == [8]
    assert api.played == []


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
