"""Инлайн-клавиатуры всех экранов бота.

Соглашение по callback_data: `<раздел>:<действие>[:<аргументы>]`. Раздел
определяет, какой роутер обработает нажатие, поэтому фильтры получаются
одним префиксом и не пересекаются между разделами.

У каждого экрана, кроме корневых, есть кнопка возврата на родительский экран:
без неё единственным способом выйти было нижнее меню, которое присылало новый
экран поверх старого.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts

BACK = "↩️ Назад"
CANCEL = "✖️ Отмена"
MENU = "🏠 Меню"

# Кнопка-заглушка календаря (пустая клетка, прошедший день, заголовок месяца).
# Telegram обязан получить callback_data у каждой кнопки, поэтому «ничего не
# делает» -- это отдельный callback, на который висит пустой ответ.
NOOP = "ui:noop"


def _mark(flag: bool) -> str:
    return "✅" if flag else "⬜"


# ---------------------------------------------------------------- главное меню
def main_menu_keyboard(*, is_admin: bool) -> InlineKeyboardMarkup:
    """Корневой экран. Раньше это была нижняя reply-клавиатура, и каждое
    нажатие оставляло в чате текстовое сообщение с названием раздела."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Запись на игры", callback_data="sg:types")
    kb.button(text="📋 Мои регистрации", callback_data="mr:list:active")
    kb.button(text="👤 Профиль", callback_data="pf:menu")
    if is_admin:
        kb.button(text="🛠️ Админ-меню", callback_data="am:menu")
    kb.adjust(1)
    return kb.as_markup()


def menu_only_keyboard() -> InlineKeyboardMarkup:
    """Единственная кнопка «Меню» -- для финальных экранов, с которых больше
    некуда идти."""
    kb = InlineKeyboardBuilder()
    kb.button(text=MENU, callback_data="mn:menu")
    return kb.as_markup()


# --------------------------------------------------------------- регистрация
def salutation_keyboard(prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for value, label in texts.SALUTATIONS.items():
        kb.button(text=label, callback_data=f"{prefix}:salutation:{value}")
    kb.adjust(2)
    return kb.as_markup()


def affiliation_keyboard(prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for value, label in texts.AFFILIATIONS.items():
        kb.button(text=label, callback_data=f"{prefix}:affiliation:{value}")
    kb.adjust(1)
    return kb.as_markup()


def favorite_role_keyboard(prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for value, label in texts.FAVORITE_ROLES.items():
        kb.button(text=label, callback_data=f"{prefix}:favorite_role:{value}")
    kb.adjust(2)
    return kb.as_markup()


def preferred_roles_keyboard(prefix: str, *, can_play: bool, can_staff: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{_mark(can_play)} Игрок", callback_data=f"{prefix}:toggle:player")
    kb.button(text=f"{_mark(can_staff)} Ведущий/судья", callback_data=f"{prefix}:toggle:staff")
    kb.button(text="Готово ✅", callback_data=f"{prefix}:save")
    kb.adjust(1)
    return kb.as_markup()


def restart_registration_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Начать заново", callback_data="nr:restart")
    return kb.as_markup()


def cancel_input_keyboard(callback_data: str) -> InlineKeyboardMarkup:
    """Экран ожидания текста: без этой кнопки выйти из ввода можно было только
    нижним меню, которое присылало ещё один экран поверх."""
    kb = InlineKeyboardBuilder()
    kb.button(text=CANCEL, callback_data=callback_data)
    return kb.as_markup()


# ------------------------------------------------------------------- профиль
PROFILE_FIELDS: tuple[tuple[str, str], ...] = (
    ("salutation", "🤵 Обращение"),
    ("full_name", "🪪 ФИО"),
    ("affiliation", "🎓 Статус по пропуску"),
    ("roles", "🎭 Роли в играх"),
    ("nickname", "🏷️ Никнейм"),
    ("age", "🎂 Возраст"),
    ("favorite_role", "🃏 Любимая роль"),
    ("experience", "📖 Опыт"),
    ("bio", "✍️ О себе"),
)

# Анкетные поля с сайта необязательны, и очистить их надо уметь: без этого
# случайно введённый возраст оставался в профиле навсегда.
CLEARABLE_FIELDS = frozenset({"age", "favorite_role", "experience", "bio"})


def profile_keyboard(*, can_resubmit: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Изменить данные", callback_data="pf:edit")
    if can_resubmit:
        kb.button(text="🔁 Отправить на повторную проверку", callback_data="pf:resubmit")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=MENU, callback_data="mn:menu"))
    return kb.as_markup()


def profile_fields_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for field, label in PROFILE_FIELDS:
        kb.button(text=label, callback_data=f"pf:field:{field}")
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text=BACK, callback_data="pf:menu"))
    return kb.as_markup()


def profile_value_keyboard(field: str, inner: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Клавиатура выбора значения + «Очистить» для необязательных полей."""
    kb = InlineKeyboardBuilder()
    for row in inner.inline_keyboard:
        kb.row(*row)
    if field in CLEARABLE_FIELDS:
        kb.row(InlineKeyboardButton(text="🗑️ Очистить", callback_data=f"pf:clear:{field}"))
    kb.row(InlineKeyboardButton(text=BACK, callback_data="pf:edit"))
    return kb.as_markup()


# --------------------------------------------------------------- запись на игры
def game_types_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for value, label in texts.GAME_TYPES.items():
        kb.button(text=label, callback_data=f"sg:type:{value}")
    kb.button(text=texts.ALL_GAMES_LABEL, callback_data=f"sg:type:{texts.ALL_GAMES}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=MENU, callback_data="mn:menu"))
    return kb.as_markup()


def registration_role_keyboard(game_type: str, *, can_play: bool, can_staff: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if can_play:
        kb.button(text=texts.REGISTRATION_ROLES["player"], callback_data=f"sg:role:{game_type}:player")
    if can_staff:
        kb.button(text=texts.REGISTRATION_ROLES["staff"], callback_data=f"sg:role:{game_type}:staff")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK, callback_data="sg:types"))
    return kb.as_markup()


def game_days_keyboard(*, game_type: str, role_kind: str, days: list[str], back_to: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for day in days:
        kb.button(text=day, callback_data=f"sg:day:{game_type}:{role_kind}:{day.replace('.', '')}")
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text=BACK, callback_data=back_to))
    return kb.as_markup()


def game_slots_keyboard(*, game_type: str, role_kind: str, games: list[dict], back_to: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for game in games:
        kb.button(
            text=_slot_label(game, role_kind),
            callback_data=f"sg:game:{game_type}:{role_kind}:{game['id']}",
        )
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK, callback_data=back_to))
    return kb.as_markup()


def _slot_label(game: dict, role_kind: str) -> str:
    if role_kind == "player":
        current, limit = int(game.get("players", 0)), int(game.get("max_players", 10))
    else:
        # Штаб игры -- один ведущий и двое судей; API считает их отдельно.
        current, limit = int(game.get("hosts", 0)) + int(game.get("judges", 0)), 3
    reserves = int(game.get("reserves", 0))
    type_label = texts.GAME_TYPES.get(game.get("game_type", ""), "")
    # Заполненный стол не прячем и отказом не встречаем: запись на него --
    # это запись в резерв, и человек должен видеть это до нажатия, а не
    # после (см. registration_service.register_for_kind на бэкенде).
    if role_kind == "player" and current >= limit:
        queue = f" ({reserves} в очереди)" if reserves else ""
        return f"{game['time']} · {type_label} · 🕒 в резерв{queue}"
    reserve_suffix = f", резерв {reserves}" if reserves else ""
    return f"{game['time']} · {type_label} · {current}/{limit}{reserve_suffix}"


# ------------------------------------------------------------ мои регистрации
def my_registrations_keyboard(items: list[dict], stage: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text=("🟢 Предстоящие" if stage == "active" else "Предстоящие"),
            callback_data="mr:list:active",
        ),
        InlineKeyboardButton(
            text=("✅ Прошедшие" if stage == "completed" else "Прошедшие"),
            callback_data="mr:list:completed",
        ),
    )
    for item in items:
        kb.row(
            InlineKeyboardButton(
                text=f"{item['day_time']} · {texts.ROSTER_ROLES.get(item['role'], item['role'])}",
                callback_data=f"mr:view:{item['game_id']}",
            )
        )
    kb.row(InlineKeyboardButton(text=MENU, callback_data="mn:menu"))
    return kb.as_markup()


def my_registration_keyboard(game_id: int, *, is_reserve: bool, can_cancel: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if can_cancel:
        kb.button(
            text="❌ Выйти из резерва" if is_reserve else "❌ Отменить запись",
            callback_data=f"mr:cancel:{game_id}",
        )
    kb.button(text=BACK, callback_data="mr:list:active")
    kb.adjust(1)
    return kb.as_markup()


# ------------------------------------------------------------------- админка
def admin_menu_keyboard(*, awaiting: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎮 Создать игровой день", callback_data="am:create")
    kb.button(text="📋 Игровые дни", callback_data="am:days")
    # Счётчик прямо в подписи: игры больше не уезжают в «Ждут оценки» сами, и
    # единственный сигнал «есть неподтверждённое» -- этот экран.
    kb.button(
        text="✅ Подтвердить проведение" + (f" ({awaiting})" if awaiting else ""),
        callback_data="am:toconfirm",
    )
    kb.button(text="📢 Анонс игр на неделю", callback_data="am:cast")
    kb.button(text="👮 Администраторы", callback_data="am:admins")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=MENU, callback_data="mn:menu"))
    return kb.as_markup()


# ------------------------------------------------------- календарь и время
_MONTHS = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)
_WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

# Час, раньше которого игры в клубе не начинаются. Сетка часов в сутках --
# 24 кнопки, из них ночные никто никогда не выбирал; список от 10:00 влезает
# в четыре ряда и читается с одного взгляда.
FIRST_HOUR = 10
LAST_HOUR = 23


def calendar_keyboard(*, year: int, month: int, today: date, back_to: str) -> InlineKeyboardMarkup:
    """Месяц целиком. Дата игрового дня набиралась текстом («06.09.2026»), и
    каждая опечатка стоила ещё одного сообщения в чате -- своего и бота.

    Прошедшие числа не кликабельны: игровой день задним числом не создают, а
    молча принять такую дату значило бы завести игру, на которую нельзя
    записаться."""
    kb = InlineKeyboardBuilder()
    previous_month = date(year, month, 1) - timedelta(days=1)
    can_go_back = date(previous_month.year, previous_month.month, 1) >= date(today.year, today.month, 1)
    next_month = date(year, month, calendar.monthrange(year, month)[1]) + timedelta(days=1)
    kb.row(
        InlineKeyboardButton(
            text="◀️" if can_go_back else " ",
            callback_data=(f"am:cal:{previous_month:%Y%m}" if can_go_back else NOOP),
        ),
        InlineKeyboardButton(text=f"{_MONTHS[month - 1]} {year}", callback_data=NOOP),
        InlineKeyboardButton(text="▶️", callback_data=f"am:cal:{next_month:%Y%m}"),
    )
    kb.row(*(InlineKeyboardButton(text=name, callback_data=NOOP) for name in _WEEKDAYS))

    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        row = []
        for day_number in week:
            if day_number == 0 or date(year, month, day_number) < today:
                row.append(InlineKeyboardButton(text="·", callback_data=NOOP))
                continue
            day = date(year, month, day_number)
            label = f"·{day_number}·" if day == today else str(day_number)
            row.append(InlineKeyboardButton(text=label, callback_data=f"am:date:{day:%d%m%Y}"))
        kb.row(*row)

    kb.row(InlineKeyboardButton(text=BACK, callback_data=back_to))
    return kb.as_markup()


def hours_keyboard(*, action: str, first: int, last: int, back_to: str) -> InlineKeyboardMarkup:
    """Целые часы [first, last]. Нарезка игрового дня всегда шла по часу, так
    что выбирать минуты было нечего -- а формат «18:00-22:00» человек всё
    равно ухитрялся написать десятком способов."""
    kb = InlineKeyboardBuilder()
    for hour in range(first, last + 1):
        kb.button(text=f"{hour:02d}:00", callback_data=f"am:{action}:{hour}")
    kb.adjust(4)
    kb.row(InlineKeyboardButton(text=BACK, callback_data=back_to))
    return kb.as_markup()


def locations_keyboard(locations: list[str], *, back_to: str) -> InlineKeyboardMarkup:
    """Места прошлых игр + ручной ввод.

    В callback_data едет индекс, а не само место: там 64 байта, а «ВМК МГУ,
    ауд. 685» -- это ещё и двоеточия, по которым разбирается callback.
    """
    kb = InlineKeyboardBuilder()
    for index, location in enumerate(locations):
        kb.button(text=f"📍 {location}", callback_data=f"am:loc:{index}")
    kb.button(text="✍️ Другое место", callback_data="am:locnew")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK, callback_data=back_to))
    return kb.as_markup()


def admin_game_types_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for value, label in texts.GAME_TYPES.items():
        kb.button(text=label, callback_data=f"am:newtype:{value}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK, callback_data="am:menu"))
    return kb.as_markup()


def admin_days_keyboard(day_cards: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for card in day_cards:
        day = str(card["day"])
        types = ", ".join(card.get("types") or [])
        kb.button(
            text=f"{day}{f' · {types}' if types else ''}",
            callback_data=f"am:day:{day.replace('.', '')}",
        )
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK, callback_data="am:menu"))
    return kb.as_markup()


def admin_day_keyboard(day_token: str, games: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for game in games:
        registered = int(game.get("players", 0)) + int(game.get("hosts", 0)) + int(game.get("judges", 0))
        kb.button(
            text=f"#{game['id']} · {game['time']} · {registered}/13",
            callback_data=f"am:game:{game['id']}",
        )
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="🗑️ Удалить весь день", callback_data=f"am:dayrm:{day_token}"))
    kb.row(InlineKeyboardButton(text=BACK, callback_data="am:days"))
    return kb.as_markup()


ADMIN_GAME_FIELDS: tuple[tuple[str, str], ...] = (
    ("starts_at", "🕒 Дата и время"),
    ("location", "📍 Место"),
    ("game_type", "🎮 Формат"),
)


def admin_game_keyboard(
    game_id: int, day_token: str, *, needs_confirmation: bool = False, back_to: str | None = None
) -> InlineKeyboardMarkup:
    """Карточка игры. У прошедшей неподтверждённой игры вместо правки полей --
    развилка «проведена / не состоялась»: без неё игра не попадёт ни в «Ждут
    оценки», ни куда-либо ещё (game_service.mark_session_played)."""
    kb = InlineKeyboardBuilder()
    if needs_confirmation:
        kb.row(InlineKeyboardButton(text="✅ Игра проведена", callback_data=f"am:played:{game_id}"))
        kb.row(InlineKeyboardButton(text="🚫 Не состоялась", callback_data=f"am:notheld:{game_id}"))
    for field, label in ADMIN_GAME_FIELDS:
        kb.button(text=label, callback_data=f"am:edit:{game_id}:{field}")
    kb.adjust(2)
    if not needs_confirmation:
        kb.row(InlineKeyboardButton(text="🗑️ Удалить игру", callback_data=f"am:rm:{game_id}"))
    kb.row(InlineKeyboardButton(text=BACK, callback_data=back_to or f"am:day:{day_token}"))
    return kb.as_markup()


def admin_awaiting_keyboard(games: list[dict]) -> InlineKeyboardMarkup:
    """Прошедшие игры, ждущие ответа «состоялась или нет»."""
    kb = InlineKeyboardBuilder()
    for game in games:
        registered = int(game.get("players", 0)) + int(game.get("hosts", 0)) + int(game.get("judges", 0))
        kb.button(
            text=f"#{game['id']} · {game['day_time']} · {registered} чел.",
            callback_data=f"am:confirm:{game['id']}",
        )
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK, callback_data="am:menu"))
    return kb.as_markup()


def admin_broadcast_keyboard(*, can_send: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if can_send:
        kb.button(text="📢 Разослать", callback_data="am:castgo")
    kb.button(text=BACK, callback_data="am:menu")
    kb.adjust(1)
    return kb.as_markup()


def announcement_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура самого анонса: кнопка ведёт в обычный экран записи, который
    и займёт это сообщение -- ещё одного в чате не появится."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Записаться", callback_data="sg:types")
    return kb.as_markup()


def admin_game_type_keyboard(game_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for value, label in texts.GAME_TYPES.items():
        kb.button(text=label, callback_data=f"am:settype:{game_id}:{value}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK, callback_data=f"am:game:{game_id}"))
    return kb.as_markup()


def admin_confirm_keyboard(*, confirm_data: str, back_data: str, label: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=label, callback_data=confirm_data)
    kb.button(text=BACK, callback_data=back_data)
    kb.adjust(1)
    return kb.as_markup()


def admin_admins_keyboard(admins: list[dict], pending: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить администратора", callback_data="am:addadmin")
    for admin in admins:
        if not admin.get("telegram_id"):
            continue
        username = f" (@{admin['telegram_username']})" if admin.get("telegram_username") else ""
        kb.button(
            text=f"➖ {admin['nickname']}{username}",
            callback_data=f"am:rmadmin:{admin['telegram_id']}",
        )
    for username in pending:
        kb.button(text=f"➖ @{username} (приглашён)", callback_data=f"am:rmpending:{username}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK, callback_data="am:menu"))
    return kb.as_markup()
