"""Админ-меню бота: права и рассылки.

Планировщик игр отсюда уехал целиком -- игровые дни, карточки игр,
подтверждение проведения и «не состоялась» живут в админке сайта, во вкладке
«Игры → Расписание» (ARCHITECTURE.md, раздел 5). В боте осталось ровно то,
чего без Telegram не сделать:

* назначить администратора -- человека часто знают только по @username, и
  telegram_id у него появится лишь при первом /start;
* анонс игр на неделю и произвольное сообщение от админа -- рассылает их бот,
  потому что токен Telegram есть только у него (раздел 12).
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
from app.api_client import ApiClient, ApiError, format_day, format_time
from app.keyboards.inline import (
    admin_admins_keyboard,
    admin_broadcast_keyboard,
    admin_menu_keyboard,
    admin_text_broadcast_keyboard,
    announcement_keyboard,
    cancel_input_keyboard,
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
def _announcement_text(games: list[dict], days: int) -> str:
    """Одно сообщение на весь список: отдельная строка на игру и один заголовок
    на день, иначе анонс превращается в простыню."""
    lines = [f"🎲 Игры на ближайшие {days} дней\n"]
    current_day = ""
    for game in games:
        day = format_day(game["starts_at"])
        if day != current_day:
            current_day = day
            lines.append(f"\n📅 {day}")
        players, limit = int(game.get("players", 0)), int(game.get("max_players", 10))
        seats = f"{limit - players} мест" if players < limit else "стол собран, есть резерв"
        lines.append(
            f"• {format_time(game['starts_at'])} — "
            f"{texts.GAME_TYPES.get(game.get('game_type', ''), '')}, "
            f"{game.get('location') or 'место уточняется'} ({seats})"
        )
    lines.append("\nНажмите «Записаться», чтобы выбрать игру.")
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
        keyboard=announcement_keyboard(),
        title="📢 Анонс.",
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
