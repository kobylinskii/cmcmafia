"""Инлайн-клавиатуры всех экранов бота.

Соглашение по callback_data: `<раздел>:<действие>[:<аргументы>]`. Раздел
определяет, какой роутер обработает нажатие, поэтому фильтры получаются
одним префиксом и не пересекаются между разделами.

У каждого экрана, кроме корневых, есть кнопка возврата на родительский экран:
без неё единственным способом выйти было нижнее меню, которое присылало новый
экран поверх старого.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts

BACK = "↩️ Назад"
CANCEL = "✖️ Отмена"
MENU = "🏠 Меню"


def _mark(flag: bool) -> str:
    return "✅" if flag else "⬜"


# ---------------------------------------------------------------- главное меню
def main_menu_keyboard(*, is_admin: bool) -> InlineKeyboardMarkup:
    """Корневой экран. Раньше это была нижняя reply-клавиатура, и каждое
    нажатие оставляло в чате текстовое сообщение с названием раздела."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Запись на игры", callback_data="sg:days")
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
    kb.button(text="Готово", callback_data=f"{prefix}:save")
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
# Порядок экранов: день -> формат (только если в этот день есть и фанки, и
# обучающие) -> роль (только если игрок готов и играть, и вести) -> игры.
# Раньше первым спрашивали формат, и человеку, который просто хочет знать,
# когда ближайшая игра, приходилось выбирать его вслепую.
#
# День едет в callback_data токеном ДДММГГГГ: двоеточия в нём -- разделители
# самой callback_data, а на всё вместе у Telegram 64 байта.
def day_token(day: str) -> str:
    return day.replace(".", "")


def game_days_keyboard(days: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for day in days:
        kb.button(text=day, callback_data=f"sg:day:{day_token(day)}")
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text=MENU, callback_data="mn:menu"))
    return kb.as_markup()


def game_types_keyboard(token: str, game_types: list[str]) -> InlineKeyboardMarkup:
    """Формат игр этого дня. Показывается, только когда их в дне больше одного."""
    kb = InlineKeyboardBuilder()
    for value in game_types:
        kb.button(text=texts.GAME_TYPES.get(value, value), callback_data=f"sg:cat:{token}:{value}")
    kb.button(text=texts.ALL_GAMES_LABEL, callback_data=f"sg:cat:{token}:{texts.ALL_GAMES}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK, callback_data="sg:days"))
    return kb.as_markup()


def registration_role_keyboard(
    token: str, game_type: str, *, can_play: bool, can_staff: bool, back_to: str
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if can_play:
        kb.button(
            text=texts.REGISTRATION_ROLES["player"],
            callback_data=f"sg:role:{token}:{game_type}:player",
        )
    if can_staff:
        kb.button(
            text=texts.REGISTRATION_ROLES["staff"],
            callback_data=f"sg:role:{token}:{game_type}:staff",
        )
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=BACK, callback_data=back_to))
    return kb.as_markup()


def game_slots_keyboard(
    *, token: str, game_type: str, role_kind: str, games: list[dict], back_to: str
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for game in games:
        kb.button(
            text=_slot_label(game, role_kind),
            callback_data=f"sg:game:{token}:{game_type}:{role_kind}:{game['id']}",
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
    # Своя запись остаётся в списке с галочкой, а не исчезает из него: раньше
    # строка после нажатия пропадала, и это читалось как «слот куда-то делся»,
    # а не «место занято мной».
    if game.get("my_role"):
        role = texts.ROSTER_ROLES.get(game["my_role"], "")
        return f"✅ {game['time']} · {type_label} · вы записаны ({role.lower()})"
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
def admin_menu_keyboard() -> InlineKeyboardMarkup:
    """Всё, что осталось от админки бота.

    Игровые дни, карточки игр и подтверждение проведения отсюда убраны:
    расписание ведут на сайте, во вкладке «Игры → Расписание». Здесь -- только
    то, для чего нужен именно Telegram (см. handlers/admin.py).
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="👮 Администраторы", callback_data="am:admins")
    kb.button(text="📢 Анонс игр на неделю", callback_data="am:cast")
    kb.button(text="✉️ Написать всем", callback_data="am:say")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text=MENU, callback_data="mn:menu"))
    return kb.as_markup()


def admin_broadcast_keyboard(*, can_send: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if can_send:
        kb.button(text="📢 Разослать", callback_data="am:castgo")
    kb.button(text=BACK, callback_data="am:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_text_broadcast_keyboard(*, can_send: bool) -> InlineKeyboardMarkup:
    """Предпросмотр произвольного сообщения. Отдельная кнопка «Изменить текст»:
    опечатку замечают именно на этом экране, и заставлять ради неё возвращаться
    в меню -- лишний шаг."""
    kb = InlineKeyboardBuilder()
    if can_send:
        kb.button(text="✉️ Разослать", callback_data="am:saygo")
    kb.button(text="✏️ Изменить текст", callback_data="am:say")
    kb.button(text=BACK, callback_data="am:menu")
    kb.adjust(1)
    return kb.as_markup()


def announcement_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура самого анонса: кнопка ведёт в обычный экран записи, который
    и займёт это сообщение -- ещё одного в чате не появится."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Записаться", callback_data="sg:days")
    return kb.as_markup()


# ------------------------------------------------------ модерация в сообщении
# Решение по заявке и по правке принимается кнопкой под тем самым сообщением,
# которым бот сообщил о новом событии. Уведомление приходит каждому админу
# своей копией: решивший увидит итог в своей, остальные -- «уже рассмотрено»
# при нажатии (бэкенд отвечает 409).
def moderation_keyboard(kind: str, item_id: int) -> InlineKeyboardMarkup:
    """kind: 'r' -- заявка на вступление, 'c' -- правка профиля."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text="✅ Подтвердить" if kind == "r" else "✅ Применить",
        callback_data=f"md:ok:{kind}:{item_id}",
    )
    kb.button(text="⛔ Отклонить", callback_data=f"md:no:{kind}:{item_id}")
    kb.adjust(2)
    return kb.as_markup()


def moderation_cancel_keyboard(kind: str, item_id: int) -> InlineKeyboardMarkup:
    """Отмена ввода причины -- возвращает сообщение к двум кнопкам решения."""
    kb = InlineKeyboardBuilder()
    kb.button(text=CANCEL, callback_data=f"md:back:{kind}:{item_id}")
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
