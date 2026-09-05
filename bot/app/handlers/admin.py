from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime, timedelta
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.api_client import ApiClient, format_day_time, format_time
from app.keyboards.inline import (
    GAME_TYPE_LABELS,
    admin_edit_game_days_keyboard,
    admin_game_days_keyboard,
    admin_games_by_day_keyboard,
)
from app.keyboards.reply import (
    admin_menu_keyboard,
    back_only_keyboard,
    game_edit_field_keyboard,
    game_type_keyboard,
    game_type_with_all_keyboard,
)
from app.states import AdminStates
from app.utils import normalize_phone

router = Router(name="admin")
BACK_BUTTONS = {"Назад", "↩️ Назад"}


async def _resolve_admin_target(raw_value: str, api: ApiClient, tg_id: int) -> tuple[int | None, str | None]:
    raw = raw_value.strip()
    if not raw:
        return None, "Введите Telegram ID, номер телефона или @username."

    if raw.lstrip("-").isdigit():
        return int(raw), None

    if raw.startswith("@"):
        user = await api.admin_lookup_by_username(tg_id, raw)
        if not user:
            return None, "Пользователь с таким @username не найден среди зарегистрированных."
        return int(user["telegram_id"]), None

    phone = normalize_phone(raw)
    if len(phone) >= 10:
        user = await api.admin_lookup_by_phone(tg_id, phone)
        if not user:
            return None, "Пользователь с таким номером не найден среди зарегистрированных."
        return int(user["telegram_id"]), None

    return None, "Неверный формат. Введите Telegram ID, номер телефона или @username."


async def _notify_about_admin_status(bot: Bot, target_tg_id: int) -> None:
    try:
        await bot.send_message(
            target_tg_id,
            "🎉 Вам выданы права администратора.\nТеперь вам доступно «Админ-меню».",
        )
    except Exception:
        # Пользователь мог ни разу не начать чат с ботом или заблокировать бота.
        pass


async def _notify_users_about_game_update(
    bot: Bot, api: ApiClient, tg_id: int, game_id: int, before: dict, after: dict
) -> None:
    changes: list[str] = []
    if before["starts_at"] != after["starts_at"]:
        changes.append(
            f"• Время игры: {format_day_time(before['starts_at'])} -> {format_day_time(after['starts_at'])}"
        )
    if before["location"] != after["location"]:
        changes.append(f"• Место: {before['location']} -> {after['location']}")

    if not changes:
        return

    text = f"📣 Обновление по игре #{game_id}\nАдмин изменил параметры игры:\n{chr(10).join(changes)}"
    roster = await api.session_roster(tg_id, game_id)
    notify_ids = {r["telegram_id"] for r in roster["registrations"] if r["telegram_id"]}
    notify_ids |= {r["telegram_id"] for r in roster["reserves"] if r["telegram_id"]}
    for user_tg_id in notify_ids:
        try:
            await bot.send_message(user_tg_id, text)
        except Exception:
            pass


def _with_time(game: dict) -> dict:
    game = dict(game)
    game["time"] = format_time(game["starts_at"])
    return game


def _to_minutes(raw: str) -> int | None:
    try:
        hh, mm = raw.split(":")
        return int(hh) * 60 + int(mm)
    except (ValueError, TypeError):
        return None


def _parse_day(raw: str) -> str | None:
    try:
        dt = datetime.strptime(raw.strip(), "%d.%m.%Y")
        return dt.strftime("%d.%m.%Y")
    except ValueError:
        return None


def _parse_time(raw: str) -> str | None:
    try:
        dt = datetime.strptime(raw.strip(), "%H:%M")
        return dt.strftime("%H:%M")
    except ValueError:
        return None


def _parse_game_type_text(raw: str, allow_all: bool = False) -> str | None:
    # Турнир сюда больше не мапится: турнирные игры создаются и оцениваются
    # только на сайте (вкладка «Турниры» в админке), бот их не заводит.
    mapping = {
        "🎉 Фанки": "funky",
        "Фанки": "funky",
        "📚 Обучающие": "training",
        "Обучающие": "training",
    }
    text = (raw or "").strip()
    if allow_all and text in {"📋 Все игры", "Все игры"}:
        return "all"
    return mapping.get(text)


async def _games_for_day_and_scope(api: ApiClient, tg_id: int, day: str, game_type: str) -> list[dict]:
    games = await api.admin_sessions_by_day(tg_id, day)
    if game_type == "all":
        return games
    return [game for game in games if game.get("game_type") == game_type]


def _parse_time_range(raw: str) -> tuple[str, str] | None:
    text = raw.replace("—", "-").replace("–", "-").strip()
    if "-" not in text:
        return None
    start_raw, end_raw = [part.strip() for part in text.split("-", maxsplit=1)]
    start_min = _to_minutes(start_raw)
    end_min = _to_minutes(end_raw)
    if start_min is None or end_min is None or end_min <= start_min:
        return None
    if (end_min - start_min) < 60:
        return None
    if start_min % 60 != 0 or end_min % 60 != 0:
        return None
    return (f"{start_min // 60:02d}:{start_min % 60:02d}", f"{end_min // 60:02d}:{end_min % 60:02d}")


def _build_hourly_starts(day: str, time_from: str, time_to: str) -> list[str]:
    start_min = _to_minutes(time_from)
    end_min = _to_minutes(time_to)
    if start_min is None or end_min is None:
        return []
    starts: list[str] = []
    current = start_min
    while current < end_min:
        starts.append(f"{day} {current // 60:02d}:{current % 60:02d}")
        current += 60
    return starts


def _username_suffix(username: str | None) -> str:
    if not username:
        return "(без @username)"
    return f"(@{username})"


async def _finish_edit_step(message: Message, confirmation_text: str) -> None:
    await message.answer(
        f"{confirmation_text}\n\nВыберите формат игр для следующего редактирования:",
        reply_markup=game_type_with_all_keyboard(),
    )


async def _require_admin(message: Message, api: ApiClient) -> bool:
    user = await api.get_profile(message.from_user.id)
    if not user or not user["is_bot_admin"]:
        await message.answer("У вас нет прав администратора.")
        return False
    return True


@router.message(F.text.in_({"Админ-меню", "🛠️ Админ-меню"}))
async def admin_menu_handler(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        return
    await state.clear()
    await message.answer("Админ-меню 🛠️", reply_markup=admin_menu_keyboard())


# ------------------------------------------------------------ add admin flow

@router.message(F.text.in_({"Добавить админа", "➕ Добавить админа"}))
async def add_admin_start(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        return
    await state.set_state(AdminStates.waiting_for_admin_to_add)
    await message.answer(
        "Введите Telegram ID, номер телефона или @username пользователя,\n"
        "которого хотите назначить администратором.",
        reply_markup=back_only_keyboard(),
    )


@router.message(AdminStates.waiting_for_admin_to_add, ~F.text.in_(BACK_BUTTONS))
async def add_admin_finish(message: Message, state: FSMContext, api: ApiClient, bot: Bot) -> None:
    if not await _require_admin(message, api):
        await state.clear()
        return

    tg_id = message.from_user.id
    raw = (message.text or "").strip()
    if raw.startswith("@"):
        username = raw.lstrip("@")
        result = await api.admin_grant(tg_id, username=username)
        await state.clear()
        if result["status"] == "granted":
            await _notify_about_admin_status(bot, result["telegram_id"])
            await message.answer(f"Администратор @{username} добавлен ✅", reply_markup=admin_menu_keyboard())
        elif result["status"] == "already_admin":
            await message.answer(
                f"Пользователь @{username} уже является администратором.", reply_markup=admin_menu_keyboard()
            )
        elif result["status"] == "pending":
            await message.answer(
                f"Пользователь @{username} пока не зарегистрирован.\n"
                "Добавила его в список ожидания: как только он зайдёт в бота —\n"
                "админ-права выдадутся автоматически ✅",
                reply_markup=admin_menu_keyboard(),
            )
        else:
            await message.answer(f"Пользователь @{username} уже есть в списке ожидания.", reply_markup=admin_menu_keyboard())
        return

    target, error = await _resolve_admin_target(raw, api, tg_id)
    if error:
        await message.answer(error)
        return

    result = await api.admin_grant(tg_id, target_telegram_id=target)
    await state.clear()
    if result["status"] == "granted":
        await _notify_about_admin_status(bot, target)
        await message.answer(f"Администратор с ID {target} добавлен ✅", reply_markup=admin_menu_keyboard())
    else:
        await message.answer(f"Пользователь с ID {target} уже является администратором.", reply_markup=admin_menu_keyboard())


# --------------------------------------------------------- remove admin flow

@router.message(F.text.in_({"Удалить админа", "➖ Удалить админа"}))
async def remove_admin_start(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        return
    admins = await api.admin_list_admins(message.from_user.id)
    ids_text = ", ".join(str(a["telegram_id"]) for a in admins if a["telegram_id"]) or "нет"
    await state.set_state(AdminStates.waiting_for_admin_to_remove)
    await message.answer(
        "Введите Telegram ID, номер телефона или @username администратора для удаления.\n"
        f"Текущие администраторы: {ids_text}",
        reply_markup=back_only_keyboard(),
    )


@router.message(AdminStates.waiting_for_admin_to_remove, ~F.text.in_(BACK_BUTTONS))
async def remove_admin_finish(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        await state.clear()
        return

    tg_id = message.from_user.id
    raw = (message.text or "").strip()
    if raw.startswith("@"):
        username = raw.lstrip("@")
        user = await api.admin_lookup_by_username(tg_id, username)
        removed_admin = False
        if user:
            target = int(user["telegram_id"])
            if target == tg_id:
                await message.answer("Нельзя удалить самого себя из администраторов.")
                return
            removed_admin = await api.admin_revoke(tg_id, target)
        removed_pending = await api.admin_revoke_pending(tg_id, username)
        await state.clear()
        if removed_admin and removed_pending:
            await message.answer(
                f"Администратор @{username} удалён. Также удалено отложенное назначение из списка ожидания.",
                reply_markup=admin_menu_keyboard(),
            )
        elif removed_admin:
            await message.answer(f"Администратор @{username} удалён.", reply_markup=admin_menu_keyboard())
        elif removed_pending:
            await message.answer(
                f"Пользователь @{username} удалён из списка ожидания на админ-права.",
                reply_markup=admin_menu_keyboard(),
            )
        else:
            await message.answer(
                f"Пользователь @{username} не найден ни среди администраторов, ни в списке ожидания.",
                reply_markup=admin_menu_keyboard(),
            )
        return

    target, error = await _resolve_admin_target(raw, api, tg_id)
    if error:
        await message.answer(error)
        return

    if target == tg_id:
        await message.answer("Нельзя удалить самого себя из администраторов.")
        return

    removed = await api.admin_revoke(tg_id, target)
    await state.clear()
    if removed:
        await message.answer(f"Администратор с ID {target} удалён.", reply_markup=admin_menu_keyboard())
    else:
        await message.answer(f"Администратор с ID {target} не найден.", reply_markup=admin_menu_keyboard())


# ----------------------------------------------------------- create game flow

@router.message(F.text.in_({"Создать игру", "🎮 Создать игру"}))
async def create_game_start(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        return
    await state.set_state(AdminStates.waiting_for_game_type)
    await message.answer("Выберите формат игр:", reply_markup=game_type_keyboard())


@router.message(AdminStates.waiting_for_game_type, ~F.text.in_(BACK_BUTTONS))
async def create_game_type(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        await state.clear()
        return

    game_type = _parse_game_type_text(message.text or "", allow_all=False)
    if not game_type:
        await message.answer("Выберите формат кнопкой: Фанки или Обучающие.")
        return

    await state.update_data(game_type=game_type)
    await state.set_state(AdminStates.waiting_for_game_day)
    await message.answer("Введите день игр в формате ДД.ММ.ГГГГ.\nПример: 21.06.2026")


@router.message(AdminStates.waiting_for_game_day, ~F.text.in_(BACK_BUTTONS))
async def create_game_day(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        await state.clear()
        return

    day = _parse_day(message.text or "")
    if not day:
        await message.answer("Неверный формат дня. Пример: 21.06.2026")
        return

    await state.update_data(game_day=day)
    await state.set_state(AdminStates.waiting_for_game_location)
    await message.answer("Введите место проведения игры.")


@router.message(AdminStates.waiting_for_game_location, ~F.text.in_(BACK_BUTTONS))
async def create_game_location(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        await state.clear()
        return

    location = (message.text or "").strip()
    if len(location) < 3:
        await message.answer("Название места должно содержать не менее 3 символов.")
        return

    await state.update_data(location=location)
    await state.set_state(AdminStates.waiting_for_game_time_range)
    await message.answer(
        "Введите временной диапазон в формате ЧЧ:ММ-ЧЧ:ММ.\n"
        "Пример: 18:00-22:00\n"
        "Каждая игра длится 1 час."
    )


@router.message(AdminStates.waiting_for_game_time_range, ~F.text.in_(BACK_BUTTONS))
async def create_game_time_range(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        await state.clear()
        return

    parsed = _parse_time_range(message.text or "")
    if not parsed:
        await message.answer(
            "Некорректный диапазон. Используйте формат ЧЧ:ММ-ЧЧ:ММ, границы по часу и минимум 1 час."
        )
        return
    time_from, time_to = parsed
    data = await state.get_data()
    game_type = data.get("game_type")
    game_day = data.get("game_day")
    location = data.get("location")
    if game_type not in GAME_TYPE_LABELS or not game_day or not location:
        await message.answer("Данные создания игры потеряны. Начните заново.")
        await state.clear()
        return

    starts = _build_hourly_starts(day=game_day, time_from=time_from, time_to=time_to)
    if not starts:
        await message.answer("Не удалось собрать слоты по заданному диапазону.")
        return

    created_ids = await api.admin_create_sessions_bulk(message.from_user.id, starts, location, game_type)
    await state.set_state(AdminStates.waiting_for_game_type)
    await message.answer(
        "Игры созданы ✅\n"
        f"Формат: {GAME_TYPE_LABELS[game_type]}\n"
        f"День: {game_day}\n"
        f"Место: {location}\n"
        f"Диапазон: {time_from}-{time_to}\n"
        f"Создано игр: {len(created_ids)} (ID: {', '.join(map(str, created_ids))})\n\n"
        "Можно сразу создать следующий игровой день.\n"
        "Выберите формат игр:",
        reply_markup=game_type_keyboard(),
    )


@router.message(F.text.in_({"Редактировать игру", "✏️ Редактировать игру"}))
async def edit_game_start(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        return
    await state.set_state(AdminStates.waiting_for_edit_game_type)
    await message.answer(
        "Выберите формат игр для редактирования или покажите все игры:",
        reply_markup=game_type_with_all_keyboard(),
    )


@router.message(AdminStates.waiting_for_edit_game_type, ~F.text.in_(BACK_BUTTONS))
async def edit_game_pick_type(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        await state.clear()
        return
    game_type = _parse_game_type_text(message.text or "", allow_all=True)
    if not game_type:
        await message.answer("Выберите формат кнопкой: Фанки, Обучающие или Все игры.")
        return
    day_cards = await api.admin_day_cards(message.from_user.id, game_type=None if game_type == "all" else game_type)
    if not day_cards:
        await message.answer("Для выбранного формата игровые дни не найдены.")
        return
    await state.update_data(edit_scope_game_type=game_type)
    await state.set_state(AdminStates.waiting_for_edit_game_day)
    lines = ["Выберите игровой день для редактирования:"]
    for card in day_cards:
        types = ", ".join(GAME_TYPE_LABELS.get(t, t) for t in card.get("types", []))
        lines.append(f"• {card['day']} | {types}" if types else f"• {card['day']}")
    await message.answer("\n".join(lines), reply_markup=admin_edit_game_days_keyboard(day_cards))
    await message.answer("Для отмены нажмите «Назад».", reply_markup=back_only_keyboard())


@router.callback_query(F.data.startswith("adm_edit_day:"))
async def edit_game_pick_day(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    user = await api.get_profile(callback.from_user.id)
    if not user or not user["is_bot_admin"]:
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return
    data = await state.get_data()
    game_type = str(data.get("edit_scope_game_type", ""))
    if game_type not in {"all", *GAME_TYPE_LABELS.keys()}:
        await callback.answer("Сначала выберите формат для редактирования.", show_alert=True)
        return
    day_token = callback.data.split(":")[1]
    day = _parse_day(f"{day_token[:2]}.{day_token[2:4]}.{day_token[4:]}")
    if not day:
        await callback.answer("Неверный формат дня.", show_alert=True)
        return
    games = await _games_for_day_and_scope(api, callback.from_user.id, day, game_type)
    if not games:
        await callback.answer("На выбранный день игр нет.", show_alert=True)
        return
    await state.update_data(edit_scope_day=day, edit_scope_game_ids=[int(game["id"]) for game in games])
    await state.set_state(AdminStates.waiting_for_edit_day_action)
    scope_label = "всех форматов" if game_type == "all" else GAME_TYPE_LABELS[game_type]
    await callback.message.answer(
        f"Выбран день {day} ({scope_label}). Что хотите изменить?",
        reply_markup=game_edit_field_keyboard(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_edit_day_action, ~F.text.in_(BACK_BUTTONS))
async def edit_game_pick_day_action(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        await state.clear()
        return
    data = await state.get_data()
    game_ids = data.get("edit_scope_game_ids") or []
    if not game_ids:
        await state.clear()
        await message.answer("Игровой день не выбран. Начните заново.")
        return
    action_map = {
        "Время": "time",
        "🕒 Время": "time",
        "Дата": "date",
        "📅 Дата": "date",
        "Место": "location",
        "📍 Место": "location",
        "Формат игры": "game_type",
        "🎮 Формат игры": "game_type",
        "Удалить игровой день": "delete_day",
        "🗑️ Удалить игровой день": "delete_day",
    }
    action = action_map.get((message.text or "").strip())
    if not action:
        await message.answer("Выберите действие кнопкой.")
        return
    if action == "delete_day":
        deleted = 0
        for game_id in game_ids:
            if await api.admin_delete_session(message.from_user.id, int(game_id)):
                deleted += 1
        await state.set_state(AdminStates.waiting_for_edit_game_type)
        await state.update_data(edit_scope_day=None, edit_scope_game_ids=[])
        await _finish_edit_step(message, f"Игровой день удалён ✅ Удалено игр: {deleted}.")
        return
    await state.update_data(edit_day_action=action)
    await state.set_state(AdminStates.waiting_for_edit_value)
    if action == "time":
        await message.answer(
            "Введите новое время старта первой игры дня в формате ЧЧ:ММ.\n"
            "Остальные игры этого дня сдвинутся по часу.",
            reply_markup=back_only_keyboard(),
        )
    elif action == "date":
        await message.answer("Введите новую дату в формате ДД.ММ.ГГГГ.", reply_markup=back_only_keyboard())
    elif action == "location":
        await message.answer("Введите новое место для всех игр выбранного дня.", reply_markup=back_only_keyboard())
    elif action == "game_type":
        await message.answer("Выберите новый формат игр для выбранного дня.", reply_markup=game_type_keyboard())


@router.message(F.text.in_({"Список игр", "📋 Список игр"}))
async def games_list_start(message: Message, state: FSMContext, api: ApiClient) -> None:
    if not await _require_admin(message, api):
        return
    day_cards = await api.admin_day_cards(message.from_user.id)
    if not day_cards:
        await message.answer("Игр пока нет.")
        return
    lines = ["Доступные игровые дни:"]
    for card in day_cards:
        types = ", ".join(GAME_TYPE_LABELS.get(t, t) for t in card.get("types", []))
        lines.append(f"• {card['day']} | {types}" if types else f"• {card['day']}")
    lines.append("")
    lines.append("Выберите день кнопкой:")
    await message.answer("\n".join(lines), reply_markup=admin_game_days_keyboard(day_cards))
    await state.update_data(admin_games_view_message_id=None)


@router.callback_query(F.data.startswith("adm_day:"))
async def games_list_pick_day(callback: CallbackQuery, api: ApiClient) -> None:
    user = await api.get_profile(callback.from_user.id)
    if not user or not user["is_bot_admin"]:
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return

    day_token = callback.data.split(":")[1]
    day = _parse_day(f"{day_token[:2]}.{day_token[2:4]}.{day_token[4:]}")
    if not day:
        await callback.answer("Неверный формат дня.", show_alert=True)
        return

    games = [_with_time(g) for g in await api.admin_sessions_by_day(callback.from_user.id, day)]
    if not games:
        await callback.answer("На выбранный день игр нет.", show_alert=True)
        return

    lines = [f"Игры на {day}:"]
    for game in games:
        game_type = GAME_TYPE_LABELS.get(game.get("game_type", ""), game.get("game_type", "-"))
        total_registered = int(game.get("players", 0)) + int(game.get("hosts", 0)) + int(game.get("judges", 0))
        lines.append(f"• #{game['id']} | {game['time']} | {game['location']} | {game_type} ({total_registered}/13)")
    lines.append("")
    lines.append("Выберите игру кнопкой:")
    await callback.message.edit_text("\n".join(lines), reply_markup=admin_games_by_day_keyboard(games))
    await callback.answer()


@router.callback_query(F.data.startswith("adm_game:"))
async def games_list_show_participants(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    user = await api.get_profile(callback.from_user.id)
    if not user or not user["is_bot_admin"]:
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return

    game_id = int(callback.data.split(":")[1])
    game = await api.get_session(callback.from_user.id, game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    roster = await api.session_roster(callback.from_user.id, game_id)
    by_role: dict[str, list[dict]] = {"host": [], "judge": [], "player": []}
    for row in roster["registrations"]:
        by_role.setdefault(row["role"], []).append(row)

    game_type = GAME_TYPE_LABELS.get(game.get("game_type", ""), game.get("game_type", "-"))
    lines = [
        f"Состав игры #{game_id}",
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
            suffix = _username_suffix(item.get("telegram_username"))
            if role == "player":
                lines.append(f"{idx}. {item['nickname']} {suffix}")
            else:
                lines.append(f"• {item['nickname']} {suffix}")
        lines.append("")

    reserves = roster.get("reserves") or []
    lines.append("Резерв:")
    if not reserves:
        lines.append("• пусто")
    else:
        for idx, item in enumerate(reserves, start=1):
            lines.append(f"{idx}. {item['nickname']}")

    text = "\n".join(lines).strip()
    data = await state.get_data()
    previous_view_message_id = data.get("admin_games_view_message_id")
    if previous_view_message_id:
        try:
            await callback.bot.edit_message_text(
                chat_id=callback.message.chat.id, message_id=int(previous_view_message_id), text=text
            )
            await callback.answer()
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                await callback.answer()
                return
    sent = await callback.message.answer(text)
    await state.update_data(admin_games_view_message_id=sent.message_id)
    await callback.answer()


@router.message(AdminStates.waiting_for_edit_value, ~F.text.in_(BACK_BUTTONS))
async def edit_game_apply(message: Message, state: FSMContext, api: ApiClient, bot: Bot) -> None:
    if not await _require_admin(message, api):
        await state.clear()
        return
    tg_id = message.from_user.id
    data = await state.get_data()
    day = data.get("edit_scope_day")
    game_type = data.get("edit_scope_game_type")
    game_ids = [int(item) for item in (data.get("edit_scope_game_ids") or [])]
    action = data.get("edit_day_action")
    if not day or not game_type or not game_ids or not action:
        await state.clear()
        await message.answer("Данные редактирования потеряны. Начните заново.")
        return

    selected_games = await _games_for_day_and_scope(api, tg_id, day, game_type)
    selected_games = [game for game in selected_games if int(game["id"]) in set(game_ids)]
    if not selected_games:
        await state.clear()
        await message.answer("Игры выбранного дня не найдены. Начните заново.")
        return

    value_raw = (message.text or "").strip()
    selected_games.sort(key=lambda row: row["starts_at"])
    scope_ids = [int(game["id"]) for game in selected_games]

    if action == "time":
        parsed_time = _parse_time(value_raw)
        if not parsed_time:
            await message.answer("Неверный формат времени. Используйте ЧЧ:ММ.")
            return
        first_dt = datetime.strptime(f"{day} {parsed_time}", "%d.%m.%Y %H:%M")
        planned_by_game: dict[int, str] = {}
        for idx, game in enumerate(selected_games):
            new_dt = first_dt + timedelta(hours=idx)
            if new_dt.strftime("%d.%m.%Y") != day:
                await message.answer("Новый диапазон времени выходит за пределы суток. Укажите более раннее время.")
                return
            planned_by_game[int(game["id"])] = new_dt.strftime("%d.%m.%Y %H:%M")
        conflicts = await api.admin_check_conflicts(tg_id, list(planned_by_game.values()), scope_ids)
        if conflicts:
            conflicts_text = "\n".join(f"• {item}" for item in conflicts)
            await message.answer(f"На выбранные дату и время уже есть игры. Изменение не применено:\n{conflicts_text}")
            return
        for game in selected_games:
            game_id = int(game["id"])
            before = dict(game)
            after = await api.admin_update_session(tg_id, game_id, starts_at=planned_by_game[game_id])
            await _notify_users_about_game_update(bot, api, tg_id, game_id, before, after)
        await state.set_state(AdminStates.waiting_for_edit_game_type)
        await state.update_data(edit_scope_day=None, edit_scope_game_ids=[], edit_day_action=None)
        await _finish_edit_step(message, "Время игр обновлено ✅")
        return

    if action == "date":
        parsed_day = _parse_day(value_raw)
        if not parsed_day:
            await message.answer("Неверный формат даты. Используйте ДД.ММ.ГГГГ.")
            return
        planned_by_game: dict[int, str] = {}
        for game in selected_games:
            time_raw = format_time(game["starts_at"])
            planned_by_game[int(game["id"])] = f"{parsed_day} {time_raw}"
        conflicts = await api.admin_check_conflicts(tg_id, list(planned_by_game.values()), scope_ids)
        if conflicts:
            conflicts_text = "\n".join(f"• {item}" for item in conflicts)
            await message.answer(f"На выбранные дату и время уже есть игры. Изменение не применено:\n{conflicts_text}")
            return
        for game in selected_games:
            game_id = int(game["id"])
            before = dict(game)
            after = await api.admin_update_session(tg_id, game_id, starts_at=planned_by_game[game_id])
            await _notify_users_about_game_update(bot, api, tg_id, game_id, before, after)
        await state.set_state(AdminStates.waiting_for_edit_game_type)
        await state.update_data(edit_scope_day=None, edit_scope_game_ids=[], edit_day_action=None)
        await _finish_edit_step(message, "Дата игр обновлена ✅")
        return

    if action == "location":
        if len(value_raw) < 3:
            await message.answer("Место должно быть не короче 3 символов.")
            return
        for game in selected_games:
            game_id = int(game["id"])
            before = dict(game)
            after = await api.admin_update_session(tg_id, game_id, location=value_raw)
            await _notify_users_about_game_update(bot, api, tg_id, game_id, before, after)
        await state.set_state(AdminStates.waiting_for_edit_game_type)
        await state.update_data(edit_scope_day=None, edit_scope_game_ids=[], edit_day_action=None)
        await _finish_edit_step(message, "Место для игрового дня обновлено ✅")
        return

    if action == "game_type":
        new_type = _parse_game_type_text(value_raw, allow_all=False)
        if not new_type:
            await message.answer("Выберите формат кнопкой: Фанки или Обучающие.")
            return
        for game in selected_games:
            await api.admin_update_session(tg_id, int(game["id"]), game_type=new_type)
        await state.set_state(AdminStates.waiting_for_edit_game_type)
        await state.update_data(edit_scope_day=None, edit_scope_game_ids=[], edit_day_action=None)
        await _finish_edit_step(message, f"Формат игр обновлён на «{GAME_TYPE_LABELS[new_type]}» ✅")
        return

    await message.answer("Неизвестное действие. Выберите действие заново.")
