"""Админ-меню бота: права и рассылки.

Планировщик игр отсюда уехал целиком -- игровые дни, карточки игр,
подтверждение проведения и «не состоялась» живут в админке сайта, во вкладке
«Игры → Расписание» (ARCHITECTURE.md, раздел 5). В боте осталось ровно то,
чего без Telegram не сделать:

* назначить администратора -- человека часто знают только по @username, и
  telegram_id у него появится лишь при первом /start;
* анонс игр на неделю и произвольное сообщение от админа -- рассылает их бот,
  потому что токен Telegram есть только у него (раздел 12).

Кнопка «🕓 На проверке» из этого же меню ведёт в handlers/moderation.py: там
заявки и правки профиля, которые, наоборот, приехали в бота с сайта.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app import texts
from app.api_client import ApiClient, ApiError, day_label, format_day, format_time, now_local
from app.keyboards.inline import (
    admin_admins_keyboard,
    admin_broadcast_keyboard,
    admin_menu_keyboard,
    admin_reminder_keyboard,
    admin_text_broadcast_keyboard,
    announcement_keyboard,
    cancel_input_keyboard,
    day_from_token,
    game_days_keyboard,
)
from app.states import AdminStates
from app.ui import consume_input, edit_screen, open_screen, screen_message
from app.utils import normalize_phone

logger = logging.getLogger(__name__)

router = Router(name="admin")

MENU_TEXT = "🛠️ Админ-меню"
ASK_ADMIN = "Кого назначить администратором? Пришлите @username, номер телефона или Telegram ID."
ASK_BROADCAST = (
    "Что разослать? Пришлите одним сообщением текст, который увидят игроки.\n\n"
    "Форматирование не сохраняется — уйдёт как обычный текст."
)

# Пауза между сообщениями рассылки. Telegram ограничивает бота примерно
# тридцатью сообщениями в секунду разным людям; на 20/с очередь уходит без
# 429, а клуб в несколько десятков человек обходится парой секунд.
BROADCAST_PAUSE_SECONDS = 0.05

# Предел одного сообщения Telegram. Более длинный текст API просто отвергнет,
# и узнать об этом на середине рассылки -- худший момент из возможных.
MAX_BROADCAST_LENGTH = 4000


async def _resolve_admin_target(raw: str, api: ApiClient, tg_id: int) -> tuple[int | None, str | None]:
    value = (raw or "").strip()
    if not value:
        return None, "Пришлите Telegram ID, номер телефона или @username."
    if value.lstrip("-").isdigit():
        return int(value), None
    if value.startswith("@"):
        user = await api.admin_lookup_by_username(tg_id, value)
        if not user:
            return None, "Пользователь с таким @username среди зарегистрированных не найден."
        return int(user["telegram_id"]), None
    phone = normalize_phone(value)
    if len(phone) >= 10:
        user = await api.admin_lookup_by_phone(tg_id, phone)
        if not user:
            return None, "Пользователь с таким номером среди зарегистрированных не найден."
        return int(user["telegram_id"]), None
    return None, "Не разобрал. Пришлите Telegram ID, номер телефона или @username."


async def _is_admin(api: ApiClient, tg_id: int) -> bool:
    user = await api.get_profile(tg_id)
    return bool(user and user["is_bot_admin"])


# --------------------------------------------------------------------- меню
@router.message(Command("admin"))
async def open_admin_menu(message: Message, state: FSMContext, api: ApiClient) -> None:
    await consume_input(message)
    if not await _is_admin(api, message.from_user.id):
        await open_screen(message, state, "У вас нет прав администратора.")
        return
    await state.set_state(None)
    await open_screen(message, state, MENU_TEXT, admin_menu_keyboard())


@router.callback_query(F.data == "am:menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    if not await _is_admin(api, callback.from_user.id):
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return
    await state.set_state(None)
    await edit_screen(callback, state, MENU_TEXT, admin_menu_keyboard())


# ---------------------------------------------------------------- рассылка
def _by_day(games: list[dict]) -> list[tuple[str, list[dict]]]:
    """Игры, разложенные по дням, в порядке расписания."""
    days: dict[str, list[dict]] = {}
    for game in games:
        days.setdefault(format_day(game["starts_at"]), []).append(game)
    return list(days.items())


def _plural(count: int, one: str, few: str, many: str) -> str:
    """«1 игра», «2 игры», «5 игр» -- русское согласование числительного."""
    if count % 100 in range(11, 15):
        return f"{count} {many}"
    return f"{count} {({1: one, 2: few, 3: few, 4: few}).get(count % 10, many)}"


def _games_count(count: int) -> str:
    return _plural(count, "игра", "игры", "игр")


def _game_line(game: dict) -> str:
    players, limit = int(game.get("players", 0)), int(game.get("max_players", 10))
    seats = (
        _plural(limit - players, "место", "места", "мест")
        if players < limit
        else "стол собран, есть резерв"
    )
    return (
        f"• {format_time(game['starts_at'])} — "
        f"{texts.GAME_TYPES.get(game.get('game_type', ''), '')}, "
        f"{game.get('location') or 'место уточняется'} ({seats})"
    )


def _announcement_text(games: list[dict], days: int) -> str:
    """Анонс на неделю -- только дни и сколько в каждом игр.

    Раньше здесь была строка на каждую игру с местом и свободными местами, и
    анонс из трёх игровых дней уезжал за экран, а решение всё равно
    принимается на уровне «в какой день я иду». Подробности человек видит на
    экране записи -- по кнопке нужного дня.
    """
    lines = [f"🎲 Игры на ближайшие {days} дней\n"]
    for day, day_games in _by_day(games):
        lines.append(f"📅 {day_label(day)} — {_games_count(len(day_games))}")
    lines.append("\nВыберите день кнопкой ниже — откроется запись.")
    return "\n".join(lines)


def _gathering_text(day: str, games: list[dict]) -> str:
    """Рассылка «собираем стол» по одному дню -- с подробностями по играм:
    зовут сюда тех, кто ещё не записан, и им как раз нужно знать, где и
    сколько мест."""
    lines = [f"🎲 Собираем игры — {day_label(day)}\n"]
    lines += [_game_line(game) for game in games]
    lines.append("\nНажмите кнопку ниже, чтобы записаться.")
    return "\n".join(lines)


def day_reminder_text(day: str, games: list[dict]) -> str:
    """«Сегодня игры» -- одно сообщение на день, а не на каждый слот.

    Место показывается у каждой игры: в один день клуб играет и на ВМК, и в
    других аудиториях, и «сегодня игры» без адреса заставляет искать его в
    переписке.
    """
    lines = [f"⏰ Сегодня игры — {day_label(day)}\n"]
    for game in games:
        type_label = texts.GAME_TYPES.get(game.get("game_type", ""), "")
        lines.append(
            f"• {format_time(game['starts_at'])} — {type_label}, "
            f"{game.get('location') or 'место уточняется'}"
        )
    lines.append("\nСостав и отмена записи — в «📋 Мои регистрации».")
    return "\n".join(lines)


async def _send_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    *,
    recipients: list[int],
    text: str,
    keyboard: InlineKeyboardMarkup | None,
    title: str,
) -> None:
    """Общая машинка обеих рассылок: отправить всем и отчитаться.

    Экран на время рассылки остаётся без кнопок: сотня сообщений уходит не
    мгновенно, и второе нажатие отправило бы всё повторно.
    """
    await edit_screen(callback, state, f"{title} Рассылаю…")
    screen = screen_message(callback)

    delivered, blocked, failed = 0, 0, 0
    for telegram_id in recipients:
        try:
            await bot.send_message(telegram_id, text, reply_markup=keyboard)
            delivered += 1
        except (TelegramForbiddenError, TelegramNotFound):
            # Человек заблокировал бота или удалил аккаунт: это не сбой
            # рассылки, а нормальная убыль -- считаем отдельно.
            blocked += 1
        except Exception:
            failed += 1
            logger.warning("Сообщение не доставлено %s", telegram_id, exc_info=True)
        await asyncio.sleep(BROADCAST_PAUSE_SECONDS)

    report = [f"{title} Разослано.\n", f"Доставлено: {delivered}"]
    if blocked:
        report.append(f"Заблокировали бота: {blocked}")
    if failed:
        report.append(f"Не удалось отправить: {failed}")
    # Правим то же сообщение напрямую: на callback уже ответили выше, а
    # второй ответ Telegram отвергает («query ID is invalid»).
    if screen is None:
        return
    with suppress(TelegramBadRequest):
        await screen.edit_text("\n".join(report), reply_markup=admin_menu_keyboard())


@router.callback_query(F.data == "am:cast")
async def broadcast_preview(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    try:
        payload = await api.admin_weekly_broadcast(callback.from_user.id)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return

    games, recipients = payload["games"], payload["recipients"]
    await state.set_state(None)

    if not games:
        await edit_screen(
            callback, state, "На ближайшую неделю игр в расписании нет — анонсировать нечего.",
            admin_broadcast_keyboard(can_send=False),
        )
        return

    preview = _announcement_text(games, payload["days"])
    await edit_screen(
        callback,
        state,
        f"Получателей: {len(recipients)} — все, кроме уже записанных на эти игры.\n\n"
        f"Текст сообщения:\n\n{preview}",
        admin_broadcast_keyboard(can_send=bool(recipients)),
    )


@router.callback_query(F.data == "am:castgo")
async def broadcast_send(callback: CallbackQuery, state: FSMContext, api: ApiClient, bot: Bot) -> None:
    try:
        payload = await api.admin_weekly_broadcast(callback.from_user.id)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return

    games = payload["games"]
    recipients = [r["telegram_id"] for r in payload["recipients"] if r.get("telegram_id")]
    if not games or not recipients:
        await edit_screen(callback, state, "Рассылать нечего или некому.", admin_menu_keyboard())
        return

    await _send_broadcast(
        callback,
        state,
        bot,
        recipients=recipients,
        text=_announcement_text(games, payload["days"]),
        keyboard=announcement_keyboard(
            (await bot.me()).username, [day for day, _ in _by_day(games)]
        ),
        title="📢 Анонс.",
    )


# --------------------------------------------- рассылка по одному дню
# Две кнопки на одной механике: «собрать» зовёт тех, кого на дне ещё нет,
# «напомнить» пишет только записавшимся. Различаются аудиторией на бэкенде
# (broadcast_service.day_recipients) и текстом -- всё остальное общее.
AUDIENCE_ABSENT = "absent"
AUDIENCE_REGISTERED = "registered"


async def _day_payload(api: ApiClient, tg_id: int, day: str, audience: str) -> tuple[list[dict], list[int]]:
    payload = await api.admin_day_broadcast(tg_id, day, audience)
    recipients = [r["telegram_id"] for r in payload["recipients"] if r.get("telegram_id")]
    return payload["games"], recipients


@router.callback_query(F.data == "am:day")
async def pick_broadcast_day(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    """Выбор дня для сбора. Дни берутся те же, что видит игрок в записи: день
    с закрытой записью звать некуда."""
    await state.set_state(None)
    days = await api.list_game_days(callback.from_user.id)
    if not days:
        await edit_screen(
            callback, state, "Открытых для записи дней нет — собирать не на что.",
            admin_broadcast_keyboard(can_send=False),
        )
        return
    await edit_screen(
        callback,
        state,
        "📣 Собрать на игровой день\n\nВыберите день — покажу текст и получателей:",
        game_days_keyboard(days, prefix="am:day", back_to="am:menu"),
    )


@router.callback_query(F.data.startswith("am:day:"))
async def gathering_preview(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    token = callback.data.split(":")[2]
    day = day_from_token(token)
    if day is None:
        await callback.answer("Некорректная дата.", show_alert=True)
        return
    try:
        games, recipients = await _day_payload(api, callback.from_user.id, day, AUDIENCE_ABSENT)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if not games:
        await edit_screen(
            callback, state, f"На {day_label(day)} открытых игр не осталось.",
            admin_broadcast_keyboard(can_send=False, back_to="am:day"),
        )
        return
    await edit_screen(
        callback,
        state,
        f"Получателей: {len(recipients)} — все, кроме записанных на этот день.\n\n"
        f"Текст сообщения:\n\n{_gathering_text(day, games)}",
        admin_broadcast_keyboard(
            can_send=bool(recipients), send_to=f"am:daygo:{token}", back_to="am:day"
        ),
    )


@router.callback_query(F.data.startswith("am:daygo:"))
async def gathering_send(callback: CallbackQuery, state: FSMContext, api: ApiClient, bot: Bot) -> None:
    token = callback.data.split(":")[2]
    day = day_from_token(token)
    if day is None:
        await callback.answer("Некорректная дата.", show_alert=True)
        return
    try:
        games, recipients = await _day_payload(api, callback.from_user.id, day, AUDIENCE_ABSENT)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if not games or not recipients:
        await edit_screen(callback, state, "Рассылать нечего или некому.", admin_menu_keyboard())
        return
    await _send_broadcast(
        callback,
        state,
        bot,
        recipients=recipients,
        text=_gathering_text(day, games),
        keyboard=announcement_keyboard((await bot.me()).username, [day]),
        title="📣 Сбор.",
    )


@router.callback_query(F.data == "am:remind")
async def reminder_preview(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    """Напоминание про сегодняшние игры.

    Раньше оно уходило само за три часа до первой игры дня. Автоматика не
    знала ни про отмену в последний момент, ни про то, что клуб уже всё
    обсудил в чате, -- теперь момент выбирает админ, он же отмечает, какие
    игры сегодня действительно состоятся.
    """
    await state.set_state(None)
    # Вход в раздел всегда начинается с «состоятся все»: прошлый выбор -- это
    # прошлое нажатие кнопки, к сегодняшнему расписанию он отношения не имеет.
    await state.update_data(am_remind_off=[])
    await _reminder_screen(callback, state, api)


@router.callback_query(F.data.startswith("am:rmg:"))
async def reminder_toggle_game(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    game_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    off = set(data.get("am_remind_off") or [])
    off.symmetric_difference_update({game_id})
    await state.update_data(am_remind_off=sorted(off))
    await _reminder_screen(callback, state, api)


async def _reminder_games(
    api: ApiClient, tg_id: int, state: FSMContext
) -> tuple[str, list[dict], list[dict], list[int]]:
    """День, все его игры, отмеченные игры и получатели по отмеченным."""
    day = now_local().strftime("%d.%m.%Y")
    payload = await api.admin_day_broadcast(tg_id, day, AUDIENCE_REGISTERED)
    games = payload["games"]
    off = set((await state.get_data()).get("am_remind_off") or [])
    chosen = [game for game in games if game["id"] not in off]
    if not chosen:
        return day, games, [], []
    if len(chosen) == len(games):
        # Отмечены все -- получатели уже посчитаны, второй запрос ни к чему.
        recipients = payload["recipients"]
    else:
        narrowed = await api.admin_day_broadcast(
            tg_id, day, AUDIENCE_REGISTERED, [game["id"] for game in chosen]
        )
        recipients = narrowed["recipients"]
    return day, games, chosen, [r["telegram_id"] for r in recipients if r.get("telegram_id")]


async def _reminder_screen(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    try:
        day, games, chosen, recipients = await _reminder_games(api, callback.from_user.id, state)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if not games:
        await edit_screen(
            callback, state, f"На сегодня ({day_label(day)}) игр в расписании нет.",
            admin_broadcast_keyboard(can_send=False),
        )
        return

    for game in games:
        game["time"] = format_time(game["starts_at"])
    if not chosen:
        text = (
            "⏰ Напоминание про сегодняшние игры\n\n"
            "Ни одна игра не отмечена — напоминать не о чем."
        )
    else:
        text = (
            f"Отмечены игры, которые сегодня состоятся: {len(chosen)} из {len(games)}.\n"
            f"Получателей: {len(recipients)} — записанные на отмеченные игры, включая резерв.\n\n"
            f"Текст сообщения:\n\n{day_reminder_text(day, chosen)}"
        )
    await edit_screen(
        callback,
        state,
        text,
        admin_reminder_keyboard(games, {game["id"] for game in chosen}, can_send=bool(recipients)),
    )


@router.callback_query(F.data == "am:remindgo")
async def reminder_send(callback: CallbackQuery, state: FSMContext, api: ApiClient, bot: Bot) -> None:
    try:
        day, _, chosen, recipients = await _reminder_games(api, callback.from_user.id, state)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if not chosen or not recipients:
        await edit_screen(callback, state, "Напоминать нечего или некому.", admin_menu_keyboard())
        return
    await state.update_data(am_remind_off=[])
    await _send_broadcast(
        callback,
        state,
        bot,
        recipients=recipients,
        # Кнопки нет намеренно: получатель уже записан, и вести его на экран
        # записи незачем -- состав и отмена живут в «Мои регистрации».
        text=day_reminder_text(day, chosen),
        keyboard=None,
        title="⏰ Напоминание.",
    )


# ------------------------------------------------ произвольное сообщение
@router.callback_query(F.data == "am:say")
async def ask_broadcast_text(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_for_broadcast_text)
    await edit_screen(callback, state, ASK_BROADCAST, cancel_input_keyboard("am:menu"))


@router.message(AdminStates.waiting_for_broadcast_text)
async def broadcast_text_received(message: Message, state: FSMContext, api: ApiClient) -> None:
    """Текст принят -- показываем его целиком и число получателей.

    Предпросмотр обязателен: опечатку в сообщении, ушедшем всему клубу, уже
    не отозвать, а отменить рассылку до нажатия «Разослать» -- можно.
    """
    await consume_input(message)
    text = (message.text or "").strip()
    if not text:
        await open_screen(
            message, state, f"Нужен текст сообщения.\n\n{ASK_BROADCAST}", cancel_input_keyboard("am:menu")
        )
        return
    if len(text) > MAX_BROADCAST_LENGTH:
        await open_screen(
            message,
            state,
            f"Слишком длинно: {len(text)} символов при пределе {MAX_BROADCAST_LENGTH}. "
            "Сократите текст и пришлите снова.",
            cancel_input_keyboard("am:menu"),
        )
        return

    try:
        audience = await api.admin_broadcast_audience(message.from_user.id)
    except ApiError as exc:
        await open_screen(message, state, f"Не удалось получить список получателей: {exc.message}", admin_menu_keyboard())
        return

    recipients = [r["telegram_id"] for r in audience["recipients"] if r.get("telegram_id")]
    await state.set_state(None)
    await state.update_data(am_say_text=text)
    await open_screen(
        message,
        state,
        f"Получателей: {len(recipients)} — все игроки клуба, кроме отклонённых.\n\n"
        f"Текст сообщения:\n\n{text}",
        admin_text_broadcast_keyboard(can_send=bool(recipients)),
    )


@router.callback_query(F.data == "am:saygo")
async def broadcast_text_send(callback: CallbackQuery, state: FSMContext, api: ApiClient, bot: Bot) -> None:
    data = await state.get_data()
    text = (data.get("am_say_text") or "").strip()
    if not text:
        await edit_screen(callback, state, "Текст потерялся, наберите его заново.", admin_menu_keyboard())
        return

    try:
        audience = await api.admin_broadcast_audience(callback.from_user.id)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return

    recipients = [r["telegram_id"] for r in audience["recipients"] if r.get("telegram_id")]
    if not recipients:
        await edit_screen(callback, state, "Рассылать некому.", admin_menu_keyboard())
        return

    # Текст забываем сразу: он уже отправляется, и повторное «Разослать» из
    # старого экрана не должно уйти клубу второй раз.
    await state.update_data(am_say_text=None)
    await _send_broadcast(
        callback,
        state,
        bot,
        recipients=recipients,
        text=text,
        keyboard=None,
        title="✉️ Сообщение.",
    )


# ------------------------------------------------------------ администраторы
async def _render_admins(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(None)
    tg_id = callback.from_user.id
    admins = await api.admin_list_admins(tg_id)
    pending = await api.admin_list_pending(tg_id)
    await edit_screen(
        callback,
        state,
        "👮 Администраторы бота\n\nНажмите на строку, чтобы снять права.\n"
        "«Приглашён» — человек ещё не открывал бота, права выдадутся при первом /start.",
        admin_admins_keyboard(admins, pending),
    )


@router.callback_query(F.data == "am:admins")
async def show_admins(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await _render_admins(callback, state, api)


@router.callback_query(F.data == "am:addadmin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_for_admin_to_add)
    await edit_screen(callback, state, ASK_ADMIN, cancel_input_keyboard("am:admins"))


@router.message(AdminStates.waiting_for_admin_to_add)
async def add_admin_finish(message: Message, state: FSMContext, api: ApiClient, bot: Bot) -> None:
    await consume_input(message)
    tg_id = message.from_user.id
    raw = (message.text or "").strip()

    # @username человека, который ещё не открывал бота, -- нормальный случай:
    # права кладутся в «приглашения» и выдаются при первом /start.
    if raw.startswith("@"):
        try:
            result = await api.admin_grant(tg_id, username=raw)
        except ApiError as exc:
            await open_screen(message, state, f"Не получилось: {exc.message}", cancel_input_keyboard("am:admins"))
            return
        await state.set_state(None)
        granted = result.get("telegram_id")
        if granted:
            await _tell_about_admin_rights(bot, int(granted))
        await open_screen(
            message,
            state,
            f"Готово: {raw} " + ("получил права ✅" if granted else "получит права при первом входе ⏳"),
            admin_menu_keyboard(),
        )
        return

    target, error = await _resolve_admin_target(raw, api, tg_id)
    if error:
        await open_screen(message, state, f"{error}\n\n{ASK_ADMIN}", cancel_input_keyboard("am:admins"))
        return

    try:
        await api.admin_grant(tg_id, target_telegram_id=target)
    except ApiError as exc:
        await open_screen(message, state, f"Не получилось: {exc.message}", cancel_input_keyboard("am:admins"))
        return

    await state.set_state(None)
    await _tell_about_admin_rights(bot, int(target))
    await open_screen(message, state, "Права администратора выданы ✅", admin_menu_keyboard())


async def _tell_about_admin_rights(bot: Bot, target_tg_id: int) -> None:
    try:
        await bot.send_message(
            target_tg_id,
            "🎉 Вам выданы права администратора. Админ-меню открывается командой /admin "
            "или кнопкой в /menu.",
        )
    except Exception:
        logger.info("Не удалось сообщить %s о правах администратора", target_tg_id)


@router.callback_query(F.data.startswith("am:rmadmin:"))
async def remove_admin(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    target = int(callback.data.split(":")[2])
    if target == callback.from_user.id:
        # Снятие прав с самого себя оставило бы клуб без администратора, если
        # он последний, и в любом случае делается не в спешке через бота.
        await callback.answer("Снять права с себя нельзя.", show_alert=True)
        return
    await api.admin_revoke(callback.from_user.id, target)
    await _render_admins(callback, state, api)


@router.callback_query(F.data.startswith("am:rmpending:"))
async def remove_pending_admin(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    username = callback.data.split(":", 2)[2]
    await api.admin_revoke_pending(callback.from_user.id, username)
    await _render_admins(callback, state, api)


# Регистрируется последним, поэтому ловит только то, что не разобрали
# обработчики выше: кнопки уехавшего планировщика («Создать игровой день»,
# календарь, карточка игры) в экранах, которые висят у админов в чате со
# времён до переезда. Без него такое нажатие просто крутило бы часики.
@router.callback_query(F.data.startswith("am:"))
async def moved_to_site(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    if not await _is_admin(api, callback.from_user.id):
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return
    await state.set_state(None)
    await edit_screen(
        callback,
        state,
        "Расписание игр теперь ведётся на сайте: «Игры → Расписание» в админке.\n\n"
        f"{MENU_TEXT}",
        admin_menu_keyboard(),
    )
