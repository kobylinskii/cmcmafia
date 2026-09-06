"""Админ-меню бота: игровые дни, подтверждение проведения, анонс и права.

Навигация та же, что и в пользовательской части: один экран на раздел, у
каждого шага «Назад». Ввод текста здесь остался ровно в двух местах -- новое
место проведения и поиск человека по @username/телефону. Всё остальное
(дата, часы, место из уже использованных) выбирается кнопками: раньше админ
набирал «06.09.2026» и «15:00-17:00» руками, и в чате оставалась колонка из
его собственных сообщений, а каждая опечатка стоила ещё одной пары.

Что бот по-прежнему НЕ умеет и не должен: турнирные игры. У них своя сетка
этапов, целиком на сайте (см. ARCHITECTURE.md, раздел 7.7).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import texts
from app.api_client import (
    ApiClient,
    ApiError,
    format_day,
    format_day_time,
    format_time,
    from_api_datetime,
    now_local,
)
from app.keyboards.inline import (
    FIRST_HOUR,
    LAST_HOUR,
    admin_admins_keyboard,
    admin_awaiting_keyboard,
    admin_broadcast_keyboard,
    admin_confirm_keyboard,
    admin_day_keyboard,
    admin_days_keyboard,
    admin_game_keyboard,
    admin_game_type_keyboard,
    admin_game_types_keyboard,
    admin_menu_keyboard,
    announcement_keyboard,
    calendar_keyboard,
    cancel_input_keyboard,
    hours_keyboard,
    locations_keyboard,
)
from app.states import AdminStates
from app.ui import consume_input, edit_screen, open_screen, screen_message
from app.utils import normalize_phone

logger = logging.getLogger(__name__)

router = Router(name="admin")

MENU_TEXT = "🛠️ Админ-меню"
ASK_LOCATION = "Где играем? Введите место — например, «ВМК МГУ, ауд. 685»."
ASK_ADMIN = "Кого назначить администратором? Пришлите @username, номер телефона или Telegram ID."
PICK_DAY = "Выберите день игр:"
PICK_FROM = "Во сколько начинается первая игра?"
PICK_LOCATION = "Где играем?"

# Пауза между сообщениями рассылки. Telegram ограничивает бота примерно
# тридцатью сообщениями в секунду разным людям; на 20/с очередь уходит без
# 429, а клуб в несколько десятков человек обходится парой секунд.
BROADCAST_PAUSE_SECONDS = 0.05


# ------------------------------------------------------------------- разбор
def _to_minutes(raw: str) -> int | None:
    try:
        hours, minutes = raw.split(":")
        return int(hours) * 60 + int(minutes)
    except (ValueError, TypeError):
        return None


def _hourly_starts(day: str, time_from: str, time_to: str) -> list[str]:
    """Границы диапазона -- целые часы, слоты нарезаются по одному в час, и
    правая граница в набор не входит: 18:00-21:00 -- это три игры."""
    start, end = _to_minutes(time_from), _to_minutes(time_to)
    if start is None or end is None:
        return []
    return [f"{day} {minute // 60:02d}:00" for minute in range(start, end, 60)]


def _day_from_token(token: str) -> str | None:
    if len(token) != 8 or not token.isdigit():
        return None
    return f"{token[:2]}.{token[2:4]}.{token[4:]}"


def _token(day: str) -> str:
    return day.replace(".", "")


def _with_time(game: dict) -> dict:
    game = dict(game)
    game["time"] = format_time(game["starts_at"])
    game["day_time"] = format_day_time(game["starts_at"])
    return game


def _needs_confirmation(game: dict) -> bool:
    """Игра прошла, но админ ещё не сказал, состоялась ли она.

    Раньше этот вопрос никто не задавал: фоновая задача сама переводила
    прошедшую игру в 'played', и в «Ждут оценки» на сайте попадало в том числе
    то, что не собралось.
    """
    return game.get("status") in {"scheduled", "registration_closed"} and (
        from_api_datetime(game["starts_at"]) <= now_local()
    )


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


async def _notify_players_about_change(
    bot: Bot, api: ApiClient, tg_id: int, game_id: int, before: dict, after: dict
) -> None:
    changes = []
    if before["starts_at"] != after["starts_at"]:
        changes.append(
            f"• Время: {format_day_time(before['starts_at'])} → {format_day_time(after['starts_at'])}"
        )
    if before.get("location") != after.get("location"):
        changes.append(f"• Место: {before.get('location') or '—'} → {after.get('location') or '—'}")
    if not changes:
        return

    text = "📣 Изменения по игре #{}\n{}".format(game_id, "\n".join(changes))
    roster = await api.session_roster(tg_id, game_id)
    recipients = {row["telegram_id"] for row in roster["registrations"] if row.get("telegram_id")}
    recipients |= {row["telegram_id"] for row in roster["reserves"] if row.get("telegram_id")}
    for recipient in recipients:
        try:
            await bot.send_message(recipient, text)
        except Exception:
            logger.warning("Не удалось уведомить %s об изменении игры %s", recipient, game_id)


async def _is_admin(api: ApiClient, tg_id: int) -> bool:
    user = await api.get_profile(tg_id)
    return bool(user and user["is_bot_admin"])


# --------------------------------------------------------------------- меню
async def _awaiting_count(api: ApiClient, tg_id: int) -> int:
    try:
        return len(await api.admin_sessions_awaiting_confirmation(tg_id))
    except ApiError:
        # Счётчик на кнопке -- подсказка, а не смысл экрана: недоступный API
        # не должен мешать открыть админку и, например, снять права.
        return 0


@router.message(Command("admin"))
async def open_admin_menu(message: Message, state: FSMContext, api: ApiClient) -> None:
    await consume_input(message)
    if not await _is_admin(api, message.from_user.id):
        await open_screen(message, state, "У вас нет прав администратора.")
        return
    await state.set_state(None)
    awaiting = await _awaiting_count(api, message.from_user.id)
    await open_screen(message, state, MENU_TEXT, admin_menu_keyboard(awaiting=awaiting))


@router.callback_query(F.data == "am:menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    if not await _is_admin(api, callback.from_user.id):
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return
    await state.set_state(None)
    awaiting = await _awaiting_count(api, callback.from_user.id)
    await edit_screen(callback, state, MENU_TEXT, admin_menu_keyboard(awaiting=awaiting))


# ------------------------------------------------------- создание игрового дня
@router.callback_query(F.data == "am:create")
async def create_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await edit_screen(callback, state, "Формат игр нового дня:", admin_game_types_keyboard())


@router.callback_query(F.data.startswith("am:newtype:"))
async def create_pick_type(callback: CallbackQuery, state: FSMContext) -> None:
    game_type = callback.data.split(":")[2]
    if game_type not in texts.GAME_TYPES:
        await callback.answer("Неизвестный формат.", show_alert=True)
        return
    await state.set_state(None)
    await state.update_data(am_flow="create", new_game_type=game_type)
    await _render_calendar(callback, state)


async def _render_calendar(callback: CallbackQuery, state: FSMContext, *, year: int | None = None, month: int | None = None) -> None:
    """Календарь текущего (или пролистанного) месяца.

    Месяц запоминается в состоянии: с экрана часов есть «Назад», и он обязан
    вернуть человека туда же, откуда тот ушёл, а не в сегодняшний месяц.
    """
    data = await state.get_data()
    today = now_local().date()
    if year is None or month is None:
        stored = data.get("am_month")
        if stored:
            year, month = int(str(stored)[:4]), int(str(stored)[4:])
        else:
            year, month = today.year, today.month
    await state.update_data(am_month=f"{year}{month:02d}")

    editing = data.get("am_flow") == "edit"
    back_to = f"am:game:{data.get('am_game_id')}" if editing else "am:create"
    title = "Новая дата игры:" if editing else PICK_DAY
    await edit_screen(callback, state, title, calendar_keyboard(year=year, month=month, today=today, back_to=back_to))


@router.callback_query(F.data == "am:pickday")
async def back_to_calendar(callback: CallbackQuery, state: FSMContext) -> None:
    await _render_calendar(callback, state)


@router.callback_query(F.data.startswith("am:cal:"))
async def flip_month(callback: CallbackQuery, state: FSMContext) -> None:
    token = callback.data.split(":")[2]
    if len(token) != 6 or not token.isdigit():
        await callback.answer()
        return
    await _render_calendar(callback, state, year=int(token[:4]), month=int(token[4:]))


@router.callback_query(F.data.startswith("am:date:"))
async def pick_date(callback: CallbackQuery, state: FSMContext) -> None:
    day = _day_from_token(callback.data.split(":")[2])
    if day is None:
        await callback.answer("Некорректная дата.", show_alert=True)
        return
    await state.update_data(new_day=day)
    data = await state.get_data()
    if data.get("am_flow") == "edit":
        await _render_hours(callback, state, action="at", first=FIRST_HOUR, last=LAST_HOUR, prompt=f"{day}. Во сколько начинается игра?")
        return
    await _render_hours(callback, state, action="from", first=FIRST_HOUR, last=LAST_HOUR, prompt=f"{day}. {PICK_FROM}")


async def _render_hours(
    callback: CallbackQuery, state: FSMContext, *, action: str, first: int, last: int, prompt: str
) -> None:
    back_to = "am:pickday" if action in {"from", "at"} else "am:pickfrom"
    await edit_screen(callback, state, prompt, hours_keyboard(action=action, first=first, last=last, back_to=back_to))


@router.callback_query(F.data == "am:pickfrom")
async def back_to_from_hours(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    day = data.get("new_day") or ""
    await _render_hours(callback, state, action="from", first=FIRST_HOUR, last=LAST_HOUR, prompt=f"{day}. {PICK_FROM}")


@router.callback_query(F.data.startswith("am:from:"))
async def pick_start_hour(callback: CallbackQuery, state: FSMContext) -> None:
    hour = int(callback.data.split(":")[2])
    await state.update_data(new_from=hour)
    data = await state.get_data()
    # Правая граница в набор не входит, поэтому последняя осмысленная -- 24:00
    # (игра, начинающаяся в 23:00). Меньше чем на час день не нарезается.
    await _render_hours(
        callback,
        state,
        action="to",
        first=hour + 1,
        last=LAST_HOUR + 1,
        prompt=f"{data.get('new_day')}, с {hour:02d}:00. До какого часа идут игры?\n\n"
        "Бот создаст по одной игре на каждый час внутри диапазона.",
    )


@router.callback_query(F.data.startswith("am:to:"))
async def pick_end_hour(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.update_data(new_to=int(callback.data.split(":")[2]))
    await _render_locations(callback, state, api)


@router.callback_query(F.data == "am:pickto")
async def back_to_end_hours(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    hour = int(data.get("new_from") or FIRST_HOUR)
    await _render_hours(
        callback,
        state,
        action="to",
        first=hour + 1,
        last=LAST_HOUR + 1,
        prompt=f"{data.get('new_day')}, с {hour:02d}:00. До какого часа идут игры?",
    )


async def _render_locations(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    locations = await api.admin_recent_locations(callback.from_user.id)
    await state.set_state(None)
    await state.update_data(am_locations=locations)
    data = await state.get_data()
    hint = f"{data.get('new_day')}, {int(data.get('new_from', 0)):02d}:00–{int(data.get('new_to', 0)):02d}:00"
    await edit_screen(callback, state, f"{hint}\n\n{PICK_LOCATION}", locations_keyboard(locations, back_to="am:pickto"))


@router.callback_query(F.data.startswith("am:loc:"))
async def pick_location(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    index = int(callback.data.split(":")[2])
    data = await state.get_data()
    locations = data.get("am_locations") or []
    if not 0 <= index < len(locations):
        await callback.answer("Это место больше не доступно, выберите другое.", show_alert=True)
        return
    await _create_day(callback.from_user.id, callback, None, state, api, locations[index])


@router.callback_query(F.data == "am:locnew")
async def ask_new_location(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_for_game_location)
    await edit_screen(callback, state, ASK_LOCATION, cancel_input_keyboard("am:pickto"))


@router.message(AdminStates.waiting_for_game_location)
async def new_location_received(message: Message, state: FSMContext, api: ApiClient) -> None:
    await consume_input(message)
    location = (message.text or "").strip()
    if not 1 <= len(location) <= 200:
        await open_screen(
            message, state, f"Место должно быть от 1 до 200 символов.\n\n{ASK_LOCATION}",
            cancel_input_keyboard("am:pickto"),
        )
        return
    await _create_day(message.from_user.id, None, message, state, api, location)


async def _create_day(
    tg_id: int,
    callback: CallbackQuery | None,
    message: Message | None,
    state: FSMContext,
    api: ApiClient,
    location: str,
) -> None:
    """Последний шаг создания игрового дня -- общий для обоих способов задать
    место (кнопкой из прошлых и вводом руками)."""
    data = await state.get_data()
    day, game_type = data.get("new_day"), data.get("new_game_type")
    hour_from, hour_to = data.get("new_from"), data.get("new_to")

    async def show(text: str, keyboard) -> None:
        if callback is not None:
            await edit_screen(callback, state, text, keyboard)
        elif message is not None:
            await open_screen(message, state, text, keyboard)

    if not (day and game_type and hour_from is not None and hour_to is not None):
        await state.set_state(None)
        await show("Данные потерялись, начнём заново.", admin_menu_keyboard())
        return

    time_from, time_to = f"{int(hour_from):02d}:00", f"{int(hour_to):02d}:00"
    starts = _hourly_starts(day, time_from, time_to)
    conflicts = await api.admin_check_conflicts(tg_id, starts)
    if conflicts:
        # Пересечение по времени -- почти всегда повторное создание уже
        # заведённого дня, а не намерение посадить два стола в одной аудитории.
        await show(
            "На это время игры уже созданы:\n"
            + "\n".join(f"• {item}" for item in conflicts)
            + "\n\nВыберите другой диапазон.",
            hours_keyboard(action="from", first=FIRST_HOUR, last=LAST_HOUR, back_to="am:pickday"),
        )
        return

    try:
        created = await api.admin_create_sessions_bulk(tg_id, starts, location, game_type)
    except ApiError as exc:
        await show(f"Не удалось создать игры: {exc.message}", admin_menu_keyboard())
        return

    await state.set_state(None)
    await show(
        f"Создано игр: {len(created)} 🎮\n"
        f"{texts.GAME_TYPES[game_type]} · {day} · {time_from}–{time_to}\n"
        f"Место: {location}",
        admin_menu_keyboard(),
    )


# ------------------------------------------------------------- игровые дни
# Экраны вынесены в функции от явных аргументов, а не вызываются друг у друга
# «подменив callback.data»: объекты aiogram — frozen-модели pydantic, и такая
# подмена падает ValidationError уже в рантайме.
async def _render_days(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(None)
    cards = await api.admin_day_cards(callback.from_user.id)
    if not cards:
        await edit_screen(callback, state, "Игровых дней пока нет.", admin_menu_keyboard())
        return
    await edit_screen(callback, state, "Игровые дни:", admin_days_keyboard(cards))


async def _render_day(callback: CallbackQuery, state: FSMContext, api: ApiClient, token: str) -> None:
    day = _day_from_token(token)
    if day is None:
        await callback.answer("Некорректная дата.", show_alert=True)
        return
    games = [_with_time(g) for g in await api.admin_sessions_by_day(callback.from_user.id, day)]
    if not games:
        # Последнюю игру дня удалили -- показывать пустой день нечего.
        await _render_days(callback, state, api)
        return
    await state.set_state(None)
    await edit_screen(callback, state, f"Игры {day}:", admin_day_keyboard(token, games))


@router.callback_query(F.data == "am:days")
async def show_days(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await _render_days(callback, state, api)


@router.callback_query(F.data.startswith("am:day:"))
async def show_day(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await _render_day(callback, state, api, callback.data.split(":")[2])


@router.callback_query(F.data.startswith("am:game:"))
async def show_game(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    game_id = int(callback.data.split(":")[2])
    await _render_game(callback, state, api, game_id)


async def _render_game(
    callback: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    game_id: int,
    *,
    alert: str | None = None,
    back_to: str | None = None,
) -> None:
    tg_id = callback.from_user.id
    game = await api.get_session(tg_id, game_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    roster = await api.session_roster(tg_id, game_id)
    day = format_day(game["starts_at"])
    await state.set_state(None)
    await state.update_data(am_game_id=game_id, am_day_token=_token(day), am_back_to=back_to)
    await edit_screen(
        callback,
        state,
        _game_text(game, roster),
        admin_game_keyboard(
            game_id, _token(day), needs_confirmation=_needs_confirmation(game), back_to=back_to
        ),
        alert=alert,
    )


STATUS_LINES: dict[str, str] = {
    "played": "✅ Проведена, ждёт оценки на сайте",
    "rated": "🏁 Оценена",
}


def _game_text(game: dict, roster: dict) -> str:
    by_role: dict[str, list[str]] = {"host": [], "judge": [], "player": []}
    for row in roster["registrations"]:
        by_role.setdefault(row["role"], []).append(row["nickname"])

    lines = [
        f"Игра #{game['id']} · {texts.GAME_TYPES.get(game.get('game_type', ''), game.get('game_type', ''))}",
        f"Когда: {format_day_time(game['starts_at'])}",
        f"Где: {game.get('location') or '—'}",
    ]
    status_line = STATUS_LINES.get(game.get("status", ""))
    if status_line:
        lines.append(status_line)
    elif _needs_confirmation(game):
        lines.append("⏳ Игра прошла — подтвердите, состоялась ли она")
    lines.append("")

    for role in ("host", "judge", "player"):
        members = by_role.get(role, [])
        lines.append(f"{texts.ROSTER_ROLES[role]}: {', '.join(members) if members else '—'}")
    reserves = [row["nickname"] for row in roster.get("reserves") or []]
    if reserves:
        lines.append(f"Резерв: {', '.join(reserves)}")
    return "\n".join(lines)


# ------------------------------------------------- подтверждение проведения
async def _render_awaiting(callback: CallbackQuery, state: FSMContext, api: ApiClient, *, alert: str | None = None) -> None:
    await state.set_state(None)
    games = [_with_time(g) for g in await api.admin_sessions_awaiting_confirmation(callback.from_user.id)]
    if not games:
        await edit_screen(
            callback, state, "Все прошедшие игры подтверждены 👌", admin_menu_keyboard(), alert=alert
        )
        return
    await edit_screen(
        callback,
        state,
        "Прошедшие игры ждут ответа: состоялась или нет.\n\n"
        "Подтверждённая игра уходит на сайт во вкладку «Ждут оценки».",
        admin_awaiting_keyboard(games),
        alert=alert,
    )


@router.callback_query(F.data == "am:toconfirm")
async def show_awaiting(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await _render_awaiting(callback, state, api)


@router.callback_query(F.data.startswith("am:confirm:"))
async def open_awaiting_game(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    game_id = int(callback.data.split(":")[2])
    await _render_game(callback, state, api, game_id, back_to="am:toconfirm")


@router.callback_query(F.data.startswith("am:played:"))
async def mark_played(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    game_id = int(callback.data.split(":")[2])
    try:
        await api.admin_mark_session_played(callback.from_user.id, game_id)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    data = await state.get_data()
    if data.get("am_back_to") == "am:toconfirm":
        await _render_awaiting(callback, state, api, alert=f"Игра #{game_id} проведена ✅")
        return
    await _render_game(callback, state, api, game_id, alert=f"Игра #{game_id} проведена ✅")


@router.callback_query(F.data.startswith("am:notheld:"))
async def confirm_not_held(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    game_id = int(callback.data.split(":")[2])
    game = await api.get_session(callback.from_user.id, game_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    registered = int(game.get("players", 0)) + int(game.get("hosts", 0)) + int(game.get("judges", 0))
    data = await state.get_data()
    back_to = data.get("am_back_to") or f"am:game:{game_id}"
    await edit_screen(
        callback,
        state,
        f"Игра #{game_id} ({format_day_time(game['starts_at'])}) не состоялась?\n\n"
        f"Записей: {registered}. Игра будет удалена вместе с ними — в статистику и рейтинг "
        "она не попадёт.",
        admin_confirm_keyboard(
            confirm_data=f"am:notheldok:{game_id}", back_data=back_to, label="🚫 Да, не состоялась"
        ),
    )


@router.callback_query(F.data.startswith("am:notheldok:"))
async def drop_not_held(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    game_id = int(callback.data.split(":")[2])
    await api.admin_delete_session(callback.from_user.id, game_id)
    data = await state.get_data()
    if data.get("am_back_to") == "am:toconfirm":
        await _render_awaiting(callback, state, api, alert="Игра удалена")
        return
    token = data.get("am_day_token")
    if token:
        await _render_day(callback, state, api, str(token))
        return
    await _render_days(callback, state, api)


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


@router.callback_query(F.data == "am:cast")
async def broadcast_preview(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    try:
        payload = await api.admin_weekly_broadcast(callback.from_user.id)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return

    games, recipients = payload["games"], payload["recipients"]
    await state.set_state(None)
    await state.update_data(am_cast_recipients=[r["telegram_id"] for r in recipients])

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

    # Экран на время рассылки остаётся без кнопок: сотня сообщений уходит не
    # мгновенно, и второе нажатие «Разослать» отправило бы всё повторно.
    await edit_screen(callback, state, "📢 Рассылаю анонс…")
    screen = screen_message(callback)

    text = _announcement_text(games, payload["days"])
    keyboard = announcement_keyboard()
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
            logger.warning("Анонс не доставлен %s", telegram_id, exc_info=True)
        await asyncio.sleep(BROADCAST_PAUSE_SECONDS)

    report = ["📢 Анонс разослан.\n", f"Доставлено: {delivered}"]
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


# ------------------------------------------------------------- правка игры
@router.callback_query(F.data.startswith("am:edit:"))
async def edit_game_field(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, raw_id, field = callback.data.split(":")
    game_id = int(raw_id)
    if field == "game_type":
        await edit_screen(callback, state, "Новый формат игры:", admin_game_type_keyboard(game_id))
        return
    if field == "starts_at":
        # Дата и время правятся тем же календарём и той же сеткой часов, что и
        # при создании дня: руками эту строку набирали в формате «ДД.ММ.ГГГГ
        # ЧЧ:ММ» и ошибались в ней чаще, чем во всех остальных полях вместе.
        await state.set_state(None)
        await state.update_data(am_flow="edit", am_game_id=game_id, am_month=None)
        await _render_calendar(callback, state)
        return
    if field != "location":
        await callback.answer("Это поле изменить нельзя.", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_edit_value)
    await state.update_data(am_game_id=game_id, am_edit_field=field)
    await edit_screen(callback, state, "Введите новое место проведения.", cancel_input_keyboard(f"am:game:{game_id}"))


@router.callback_query(F.data.startswith("am:at:"))
async def apply_new_start(callback: CallbackQuery, state: FSMContext, api: ApiClient, bot: Bot) -> None:
    hour = int(callback.data.split(":")[2])
    data = await state.get_data()
    game_id, day = data.get("am_game_id"), data.get("new_day")
    if not game_id or not day:
        await callback.answer("Игра не выбрана.", show_alert=True)
        return

    tg_id = callback.from_user.id
    before = await api.get_session(tg_id, int(game_id))
    try:
        after = await api.admin_update_session(tg_id, int(game_id), starts_at=f"{day} {hour:02d}:00")
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if before:
        await _notify_players_about_change(bot, api, tg_id, int(game_id), before, after)
    await state.update_data(am_flow=None)
    await _render_game(callback, state, api, int(game_id), alert="Время изменено ✅")


@router.message(AdminStates.waiting_for_edit_value)
async def apply_game_edit(message: Message, state: FSMContext, api: ApiClient, bot: Bot) -> None:
    await consume_input(message)
    data = await state.get_data()
    game_id, field = data.get("am_game_id"), data.get("am_edit_field")
    if not game_id or field != "location":
        await state.set_state(None)
        await open_screen(message, state, "Игра не выбрана.", admin_menu_keyboard())
        return

    value = (message.text or "").strip()
    if not 1 <= len(value) <= 200:
        await open_screen(
            message, state, "Место должно быть от 1 до 200 символов.",
            cancel_input_keyboard(f"am:game:{game_id}"),
        )
        return

    tg_id = message.from_user.id
    before = await api.get_session(tg_id, game_id)
    try:
        after = await api.admin_update_session(tg_id, game_id, location=value)
    except ApiError as exc:
        await open_screen(
            message, state, f"Не удалось сохранить: {exc.message}", cancel_input_keyboard(f"am:game:{game_id}")
        )
        return

    if before:
        await _notify_players_about_change(bot, api, tg_id, game_id, before, after)

    await state.set_state(None)
    roster = await api.session_roster(tg_id, game_id)
    day = format_day(after["starts_at"])
    await open_screen(
        message,
        state,
        f"Сохранено ✅\n\n{_game_text(after, roster)}",
        admin_game_keyboard(game_id, _token(day), needs_confirmation=_needs_confirmation(after)),
    )


@router.callback_query(F.data.startswith("am:settype:"))
async def set_game_type(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    _, _, raw_id, game_type = callback.data.split(":")
    if game_type not in texts.GAME_TYPES:
        await callback.answer("Неизвестный формат.", show_alert=True)
        return
    try:
        await api.admin_update_session(callback.from_user.id, int(raw_id), game_type=game_type)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await _render_game(callback, state, api, int(raw_id), alert="Формат изменён ✅")


@router.callback_query(F.data.startswith("am:rm:"))
async def confirm_remove_game(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    game_id = int(callback.data.split(":")[2])
    game = await api.get_session(callback.from_user.id, game_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    registered = int(game.get("players", 0)) + int(game.get("hosts", 0)) + int(game.get("judges", 0))
    await edit_screen(
        callback,
        state,
        f"Удалить игру #{game_id} ({format_day_time(game['starts_at'])})?\n\n"
        f"Записано человек: {registered}. Их записи исчезнут вместе с игрой.",
        admin_confirm_keyboard(
            confirm_data=f"am:rmok:{game_id}", back_data=f"am:game:{game_id}", label="🗑️ Да, удалить"
        ),
    )


@router.callback_query(F.data.startswith("am:rmok:"))
async def remove_game(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    game_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    token = data.get("am_day_token")
    await api.admin_delete_session(callback.from_user.id, game_id)
    if token:
        await _render_day(callback, state, api, str(token))
        return
    await _render_days(callback, state, api)


@router.callback_query(F.data.startswith("am:dayrm:"))
async def confirm_remove_day(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    token = callback.data.split(":")[2]
    day = _day_from_token(token)
    if day is None:
        await callback.answer("Некорректная дата.", show_alert=True)
        return
    games = await api.admin_sessions_by_day(callback.from_user.id, day)
    await edit_screen(
        callback,
        state,
        f"Удалить все игры за {day}? Это {len(games)} шт. вместе со всеми записями.",
        admin_confirm_keyboard(
            confirm_data=f"am:dayrmok:{token}", back_data=f"am:day:{token}", label="🗑️ Да, удалить день"
        ),
    )


@router.callback_query(F.data.startswith("am:dayrmok:"))
async def remove_day(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    token = callback.data.split(":")[2]
    day = _day_from_token(token)
    if day is None:
        await callback.answer("Некорректная дата.", show_alert=True)
        return
    tg_id = callback.from_user.id
    for game in await api.admin_sessions_by_day(tg_id, day):
        await api.admin_delete_session(tg_id, game["id"])
    await _render_days(callback, state, api)


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
