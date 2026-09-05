import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from datetime import datetime

from app.api_client import ApiClient, format_day, format_day_time, format_time
from app.keyboards.inline import (
    ALL_GAMES_TOKEN,
    GAME_TYPE_LABELS,
    game_days_keyboard,
    game_detail_keyboard,
    game_slots_keyboard,
    game_types_keyboard,
    join_reserve_keyboard,
    registration_role_keyboard,
    user_registrations_keyboard,
)

logger = logging.getLogger(__name__)

router = Router(name="schedule")


def _restore_day(token: str) -> str | None:
    if len(token) != 8 or not token.isdigit():
        return None
    return f"{token[:2]}.{token[2:4]}.{token[4:]}"


def _role_kind_label(role: str) -> str:
    return "Игрок" if role == "player" else "Ведущий/судья"


def _game_type_title(game_type: str) -> str:
    if game_type == ALL_GAMES_TOKEN:
        return "Все форматы"
    return GAME_TYPE_LABELS[game_type]


def _is_valid_game_type(game_type: str) -> bool:
    return game_type == ALL_GAMES_TOKEN or game_type in GAME_TYPE_LABELS


def _filter_registrations_by_stage(items: list[dict], stage: str) -> list[dict]:
    now = datetime.now()
    filtered: list[dict] = []
    for item in items:
        starts_at = datetime.strptime(format_day_time(item["starts_at"]), "%d.%m.%Y %H:%M")
        is_completed = starts_at <= now
        if stage == "completed" and is_completed:
            filtered.append(item)
        if stage == "active" and not is_completed:
            filtered.append(item)
    return filtered


def _my_registrations_text(stage: str, visible_items: list[dict]) -> str:
    stage_label = "действующие" if stage == "active" else "завершенные"
    lines = [
        "Ваши регистрации.",
        "Нажмите на игру, чтобы увидеть подробности и при необходимости отменить запись.",
        f"Сейчас показаны: {stage_label}.",
    ]
    if not visible_items:
        lines.append("В этом разделе пока нет игр.")
    return "\n".join(lines)


def _game_participants_text(game: dict, roster: dict) -> str:
    by_role: dict[str, list[dict]] = {"host": [], "judge": [], "player": []}
    for row in roster["registrations"]:
        by_role.setdefault(row["role"], []).append(row)
    game_type = GAME_TYPE_LABELS.get(game.get("game_type", ""), game.get("game_type", "-"))
    lines = [
        f"Состав игры #{game['id']}",
        f"Когда: {format_day_time(game['starts_at'])}",
        f"Где: {game['location']}",
        f"Тип: {game_type}",
        "",
    ]
    role_titles = {"host": "Ведущий", "judge": "Судья", "player": "Игроки"}
    for role in ("host", "judge", "player"):
        items = by_role.get(role, [])
        lines.append(f"{role_titles[role]}:")
        if not items:
            lines.append("• пока никого")
            continue
        for idx, item in enumerate(items, start=1):
            if role == "player":
                lines.append(f"{idx}. {item['nickname']}")
            else:
                lines.append(f"• {item['nickname']}")
        lines.append("")
    reserves = roster.get("reserves") or []
    if reserves:
        lines.append("Резерв:")
        for idx, item in enumerate(reserves, start=1):
            lines.append(f"{idx}. {item['nickname']}")
    return "\n".join(lines).strip()


@router.message(F.text.in_({"📝 Регистрация на игры", "🎭 Расписание игр", "Расписание игр"}))
async def start_registration_menu(message: Message, api: ApiClient) -> None:
    if not await api.get_profile(message.from_user.id):
        await message.answer("Сначала пройдите регистрацию: /start")
        return
    await message.answer("Выберите формат игр:", reply_markup=game_types_keyboard())


@router.callback_query(F.data.startswith("reg_type:"))
async def pick_game_type(callback: CallbackQuery, api: ApiClient) -> None:
    user = await api.get_profile(callback.from_user.id)
    if not user:
        await callback.answer("Сначала пройдите регистрацию: /start", show_alert=True)
        return
    _, game_type = callback.data.split(":")
    if not _is_valid_game_type(game_type):
        await callback.answer("Неизвестный формат игр.", show_alert=True)
        return
    can_play = bool(user.get("can_play"))
    can_staff = bool(user.get("can_staff"))
    if can_play and can_staff:
        await callback.message.answer(
            f"{_game_type_title(game_type)}: выберите роль для регистрации.",
            reply_markup=registration_role_keyboard(can_play=True, can_staff=True, game_type=game_type),
        )
    elif can_play or can_staff:
        days = await api.list_game_days(callback.from_user.id, game_type=game_type)
        if not days:
            await callback.message.answer(
                f"Для формата «{_game_type_title(game_type)}» нет доступных дней для новой регистрации."
            )
        else:
            role_kind = "player" if can_play else "staff"
            await callback.message.answer(
                f"{_game_type_title(game_type)}: выберите день.",
                reply_markup=game_days_keyboard(game_type=game_type, role_kind=role_kind, days=days),
            )
    else:
        await callback.message.answer(
            "У вас не выбраны роли для регистрации. Обратитесь к администратору."
        )
    await callback.answer()


@router.callback_query(F.data.startswith("reg_role:"))
async def pick_registration_role(callback: CallbackQuery, api: ApiClient) -> None:
    if not await api.get_profile(callback.from_user.id):
        await callback.answer("Сначала пройдите регистрацию: /start", show_alert=True)
        return
    _, game_type, role_kind = callback.data.split(":")
    if not _is_valid_game_type(game_type) or role_kind not in {"player", "staff"}:
        await callback.answer("Некорректный выбор.", show_alert=True)
        return
    days = await api.list_game_days(callback.from_user.id, game_type=game_type)
    if not days:
        await callback.answer("Нет доступных дней для новой регистрации.", show_alert=True)
        return
    await callback.message.answer(
        f"{_game_type_title(game_type)} ({_role_kind_label(role_kind)}): выберите день.",
        reply_markup=game_days_keyboard(game_type=game_type, role_kind=role_kind, days=days),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("reg_day:"))
async def pick_registration_day(callback: CallbackQuery, api: ApiClient) -> None:
    if not await api.get_profile(callback.from_user.id):
        await callback.answer("Сначала пройдите регистрацию: /start", show_alert=True)
        return
    _, game_type, role_kind, day_token = callback.data.split(":")
    day = _restore_day(day_token)
    if not day:
        await callback.answer("Некорректный день.", show_alert=True)
        return
    games = await api.list_open_sessions(callback.from_user.id, game_type=game_type, day=day)
    games = [_with_time(g) for g in games]
    if not games:
        await callback.answer("На выбранный день нет доступных игр для новой регистрации.", show_alert=True)
        return
    await callback.message.answer(
        f"{_game_type_title(game_type)}, {day}. Выберите игру:",
        reply_markup=game_slots_keyboard(game_type=game_type, role_kind=role_kind, games=games),
    )
    await callback.answer()


def _with_time(game: dict) -> dict:
    game = dict(game)
    game["time"] = format_time(game["starts_at"])
    return game


@router.callback_query(F.data.startswith("reg_game:"))
async def register_for_game(callback: CallbackQuery, api: ApiClient) -> None:
    tg_id = callback.from_user.id
    user = await api.get_profile(tg_id)
    if not user:
        await callback.answer("Сначала пройдите регистрацию: /start", show_alert=True)
        return
    _, game_type, role_kind, game_id_raw = callback.data.split(":")
    if not _is_valid_game_type(game_type):
        await callback.answer("Некорректный формат игр.", show_alert=True)
        return
    game_id = int(game_id_raw)
    game = await api.get_session(tg_id, game_id)
    if not game or (game_type != ALL_GAMES_TOKEN and game.get("game_type") != game_type):
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if not game["is_open"]:
        await callback.answer("Регистрация на эту игру закрыта.", show_alert=True)
        return
    if role_kind == "player" and not user.get("can_play"):
        await callback.answer("У вас нет доступа к роли «Игрок».", show_alert=True)
        return
    if role_kind == "staff" and not user.get("can_staff"):
        await callback.answer("У вас нет доступа к роли «Ведущий/судья».", show_alert=True)
        return

    result = await api.register_for_session(tg_id, game_id, role_kind)
    if not result["ok"] and result.get("reason") == "role_full":
        await callback.message.answer(
            f"{result['message']}\nХотите встать в резерв? Если освободится место, "
            "мы автоматически запишем вас игроком.",
            reply_markup=join_reserve_keyboard(game_id),
        )
        await callback.answer()
        return

    day = format_day(game["starts_at"])
    games = [_with_time(g) for g in await api.list_open_sessions(tg_id, game_type=game_type, day=day)]
    if not games:
        try:
            await callback.message.edit_text(
                f"{_game_type_title(game_type)}, {day}. Все доступные игры на этот день уже выбраны ✅",
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        await callback.answer(result["message"])
        return
    try:
        await callback.message.edit_text(
            f"{_game_type_title(game_type)}, {day}. Выберите игру:",
            reply_markup=game_slots_keyboard(game_type=game_type, role_kind=role_kind, games=games),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
    await callback.answer(result["message"])


@router.callback_query(F.data.startswith("reg_reserve:"))
async def join_reserve(callback: CallbackQuery, api: ApiClient) -> None:
    tg_id = callback.from_user.id
    if not await api.get_profile(tg_id):
        await callback.answer("Сначала пройдите регистрацию: /start", show_alert=True)
        return
    game_id = int(callback.data.split(":")[1])
    if not await api.get_session(tg_id, game_id):
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    result = await api.reserve_for_session(tg_id, game_id)
    if result["ok"]:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
    await callback.answer(result["message"], show_alert=True)


@router.message(F.text.in_({"📋 Ваши регистрации", "📋 Список игр"}))
async def my_registrations(message: Message, state: FSMContext, api: ApiClient) -> None:
    tg_id = message.from_user.id
    if not await api.get_profile(tg_id):
        await message.answer("Сначала пройдите регистрацию: /start")
        return
    stage = "active"
    items = await api.my_registrations(tg_id)
    visible_items = _filter_registrations_by_stage(items, stage)
    sent = await message.answer(
        _my_registrations_text(stage, visible_items),
        reply_markup=user_registrations_keyboard(visible_items, stage),
    )
    await state.update_data(
        my_registrations_message_id=sent.message_id,
        my_registrations_stage=stage,
        my_registrations_view_message_id=None,
    )


@router.callback_query(F.data.startswith("myreg_stage:"))
async def switch_my_registrations_stage(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    tg_id = callback.from_user.id
    if not await api.get_profile(tg_id):
        await callback.answer("Сначала пройдите регистрацию: /start", show_alert=True)
        return
    stage = callback.data.split(":")[1]
    if stage not in {"active", "completed"}:
        await callback.answer("Некорректный этап.", show_alert=True)
        return
    items = await api.my_registrations(tg_id)
    visible_items = _filter_registrations_by_stage(items, stage)
    try:
        await callback.message.edit_text(
            _my_registrations_text(stage, visible_items),
            reply_markup=user_registrations_keyboard(visible_items, stage),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
    await state.update_data(my_registrations_stage=stage)
    await callback.answer()


@router.callback_query(F.data.startswith("myreg_view:"))
async def show_my_registration_game_participants(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    tg_id = callback.from_user.id
    if not await api.get_profile(tg_id):
        await callback.answer("Сначала пройдите регистрацию: /start", show_alert=True)
        return
    game_id = int(callback.data.split(":")[1])

    mine = await api.my_registrations(tg_id)
    own = next((item for item in mine if item["game_id"] == game_id), None)
    if own is None:
        await callback.answer("Вы не зарегистрированы на эту игру.", show_alert=True)
        return
    is_reserve = own["is_reserve"]

    game = await api.get_session(tg_id, game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    roster = await api.session_roster(tg_id, game_id)
    text = _game_participants_text(game, roster)
    keyboard = game_detail_keyboard(game_id, is_reserve)
    data = await state.get_data()
    previous_view_message_id = data.get("my_registrations_view_message_id")
    if previous_view_message_id:
        try:
            await callback.bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=int(previous_view_message_id),
                text=text,
                reply_markup=keyboard,
            )
            await callback.answer()
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                await callback.answer()
                return
    sent = await callback.message.answer(text, reply_markup=keyboard)
    await state.update_data(my_registrations_view_message_id=sent.message_id)
    await callback.answer()


@router.callback_query(F.data.startswith("myreg_cancel:"))
async def cancel_my_registration(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    tg_id = callback.from_user.id
    if not await api.get_profile(tg_id):
        await callback.answer("Сначала пройдите регистрацию: /start", show_alert=True)
        return
    parts = callback.data.split(":")
    game_id = int(parts[1])
    is_reserve = len(parts) > 2 and parts[2] == "reserve"

    result = await api.cancel_registration(tg_id, game_id)
    if not result["ok"]:
        await callback.answer("Вы не зарегистрированы на эту игру.", show_alert=True)
        return

    if result.get("promoted_telegram_id"):
        try:
            await callback.bot.send_message(
                result["promoted_telegram_id"],
                f"🎉 Освободилось место игрока в игре #{game_id} — вы переведены из резерва в основной состав!",
            )
        except Exception:
            logger.warning(
                "Не удалось уведомить пользователя %s о продвижении из резерва", result["promoted_telegram_id"]
            )

    await callback.answer("Вы удалены из резерва." if is_reserve else "Регистрация отменена.")
    try:
        await callback.message.edit_text(
            "Вы вышли из резерва на эту игру." if is_reserve else "Регистрация на эту игру отменена."
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    data = await state.get_data()
    list_message_id = data.get("my_registrations_message_id")
    if not list_message_id:
        return
    current_stage = data.get("my_registrations_stage", "active")
    if current_stage not in {"active", "completed"}:
        current_stage = "active"
    items = await api.my_registrations(tg_id)
    visible_items = _filter_registrations_by_stage(items, current_stage)
    try:
        await callback.bot.edit_message_text(
            chat_id=callback.message.chat.id,
            message_id=int(list_message_id),
            text=_my_registrations_text(current_stage, visible_items),
            reply_markup=user_registrations_keyboard(visible_items, current_stage),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


@router.message(F.text.in_({"Статистика", "📊 Статистика"}))
async def statistics_stub_handler(message: Message) -> None:
    await message.answer(
        "📊 Статистика\n"
        "Полная статистика и рейтинг доступны на сайте клуба — раздел /mafia."
    )
