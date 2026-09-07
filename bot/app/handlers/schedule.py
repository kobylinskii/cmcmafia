"""Запись на игры и свои регистрации.

Оба раздела -- цепочки экранов, живущие в одном сообщении: день -> формат ->
роль -> игра, и список регистраций -> состав игры. Каждый экран умеет
вернуться назад, поэтому в чате не остаётся ни одной клавиатуры прошлого шага.
Именно здесь старый бот плодил их больше всего: четыре шага записи -- четыре
сообщения, и все с рабочими кнопками.

Промежуточные экраны показываются только когда есть из чего выбирать: формат
-- если в этот день идут и фанки, и обучающие; роль -- если игрок готов и
играть, и вести. Вопрос с единственным ответом человек всё равно не решает.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import texts
from app.api_client import (
    ApiClient,
    ApiError,
    format_day_time,
    format_time,
    from_api_datetime,
    now_local,
)
from app.handlers.common import require_profile
from app.keyboards.inline import (
    game_days_keyboard,
    game_slots_keyboard,
    game_types_keyboard,
    my_registration_keyboard,
    my_registrations_keyboard,
    registration_role_keyboard,
)
from app.ui import consume_input, edit_screen, open_screen

logger = logging.getLogger(__name__)

router = Router(name="schedule")

PICK_DAY = "📝 Запись на игры\n\nВыберите день:"
NO_GAMES = "Свободных игр для записи сейчас нет."
NO_ROLES = (
    "В профиле не отмечено ни одной роли. Откройте «Профиль» и выберите, "
    "за кого вы готовы играть."
)


def _day_from_token(token: str) -> str | None:
    if len(token) != 8 or not token.isdigit():
        return None
    return f"{token[:2]}.{token[2:4]}.{token[4:]}"


def _with_time(game: dict) -> dict:
    game = dict(game)
    game["time"] = format_time(game["starts_at"])
    return game


# ------------------------------------------------------------ запись на игры
async def _days_screen(callback_or_message, state, api: ApiClient, tg_id: int, *, edit: bool, alert: str | None = None) -> None:
    days = await api.list_game_days(tg_id)
    text = PICK_DAY if days else NO_GAMES
    keyboard = game_days_keyboard(days)
    if edit:
        await edit_screen(callback_or_message, state, text, keyboard, alert=alert)
    else:
        await open_screen(callback_or_message, state, text, keyboard)


@router.message(Command("games"))
async def start_registration(message: Message, state: FSMContext, api: ApiClient) -> None:
    await consume_input(message)
    if not await require_profile(message, state, api):
        return
    await state.set_state(None)
    await _days_screen(message, state, api, message.from_user.id, edit=False)


# "sg:types" -- корневой экран прошлой версии (сначала спрашивали формат).
# Такие клавиатуры висят в чатах, и нажатие на них должно вести в новый первый
# экран, а не крутить часики.
@router.callback_query(F.data.in_({"sg:days", "sg:types"}))
async def back_to_days(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(None)
    await _days_screen(callback, state, api, callback.from_user.id, edit=True)


async def _show_day(
    callback: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    *,
    token: str,
    game_type: str | None = None,
    role_kind: str | None = None,
    alert: str | None = None,
) -> None:
    """Один проход по цепочке «день -> формат -> роль -> игры».

    Собран в одну функцию, а не в три обработчика: шаги пропускаются, когда
    выбирать не из чего, и после каждой записи экран перерисовывается с того
    же места. Тремя отдельными путями это разъезжалось бы на каждом шаге.
    """
    day = _day_from_token(token)
    if day is None:
        await callback.answer("Некорректная дата.", show_alert=True)
        return

    tg_id = callback.from_user.id
    games = [_with_time(g) for g in await api.list_open_sessions(tg_id, day=day)]
    if not games:
        await _days_screen(
            callback, state, api, tg_id, edit=True, alert="На этот день игр не осталось"
        )
        return

    # Шаг 1: формат. Спрашиваем, только если в дне есть и фанки, и обучающие.
    present = sorted({g["game_type"] for g in games})
    if game_type is None:
        if len(present) > 1:
            await edit_screen(
                callback,
                state,
                f"📅 {day}\n\nКакие игры показать?",
                game_types_keyboard(token, present),
                alert=alert,
            )
            return
        game_type = present[0]
    if game_type != texts.ALL_GAMES:
        games = [g for g in games if g["game_type"] == game_type]

    # Куда ведёт «Назад» с двух следующих экранов: на предыдущий ПОКАЗАННЫЙ,
    # а не на предыдущий по схеме -- иначе кнопка возвращала бы на экран,
    # который тут же снова пропускается, и выглядела бы неработающей.
    after_type = f"sg:day:{token}" if len(present) > 1 else "sg:days"

    # Шаг 2: роль. Спрашиваем, только если игрок готов и играть, и вести.
    # Профиль читается всегда, а не только когда роль ещё не выбрана: от него
    # зависит и «Назад» со списка игр. Иначе после записи (роль уже известна)
    # эта кнопка вела бы на экран роли, которого игроку с одной ролью не
    # показывали, -- и первое нажатие выглядело бы холостым.
    user = await api.get_profile(tg_id)
    if user is None:
        await callback.answer("Профиль не найден, начните с /start.", show_alert=True)
        return
    can_play, can_staff = bool(user.get("can_play")), bool(user.get("can_staff"))
    if not (can_play or can_staff):
        await callback.answer(NO_ROLES, show_alert=True)
        return
    both_roles = can_play and can_staff

    if role_kind is None:
        if both_roles:
            await edit_screen(
                callback,
                state,
                f"📅 {day} · {texts.game_type_title(game_type)}\n\nВ какой роли записываемся?",
                registration_role_keyboard(
                    token, game_type, can_play=True, can_staff=True, back_to=after_type
                ),
                alert=alert,
            )
            return
        role_kind = "player" if can_play else "staff"
    after_role = f"sg:cat:{token}:{game_type}" if both_roles else after_type

    await edit_screen(
        callback,
        state,
        f"📅 {day} · {texts.game_type_title(game_type)} · "
        f"{texts.REGISTRATION_ROLES.get(role_kind, '')}\n\n"
        "Нажмите на игру, чтобы записаться.\n"
        "Собранный стол помечен «в резерв» — запись на него ставит в очередь.",
        game_slots_keyboard(
            token=token, game_type=game_type, role_kind=role_kind, games=games, back_to=after_role
        ),
        alert=alert,
    )


@router.callback_query(F.data.startswith("sg:day:"))
async def pick_day(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await _show_day(callback, state, api, token=callback.data.split(":")[2])


@router.callback_query(F.data.startswith("sg:cat:"))
async def pick_type(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    _, _, token, game_type = callback.data.split(":")
    if not texts.is_known_game_type(game_type):
        await callback.answer("Неизвестный формат игр.", show_alert=True)
        return
    await _show_day(callback, state, api, token=token, game_type=game_type)


@router.callback_query(F.data.startswith("sg:role:"))
async def pick_role(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    _, _, token, game_type, role_kind = callback.data.split(":")
    if not texts.is_known_game_type(game_type) or role_kind not in texts.REGISTRATION_ROLES:
        await callback.answer("Некорректный выбор.", show_alert=True)
        return
    await _show_day(callback, state, api, token=token, game_type=game_type, role_kind=role_kind)


@router.callback_query(F.data.startswith("sg:game:"))
async def register_for_game(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    _, _, token, game_type, role_kind, raw_id = callback.data.split(":")
    tg_id = callback.from_user.id
    game = await api.get_session(tg_id, int(raw_id))
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    # Своя запись осталась в списке с галочкой -- повторное нажатие ничего не
    # меняет, но и молчать на него нельзя: отменяют запись в «Мои регистрации».
    if game.get("my_role"):
        await callback.answer(
            f"Вы уже записаны на игру #{game['id']} ✅\n"
            "Отменить запись можно в «📋 Мои регистрации».",
            show_alert=True,
        )
        return
    if not game["is_open"]:
        await callback.answer("Запись на эту игру уже закрыта.", show_alert=True)
        return

    try:
        result = await api.register_for_session(tg_id, game["id"], role_kind)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return

    if not result["ok"]:
        await callback.answer(result["message"], show_alert=True)
        return

    # Запись в штаб могла освободить место за столом и поднять первого из
    # очереди -- ему надо написать так же, как при отмене чужой записи.
    await _notify_promoted(callback, game["id"], result)

    if result.get("is_reserve"):
        # Отдельного экрана «мест нет» больше нет: стол на десять человек
        # собирается первым, одиннадцатый тем же нажатием встаёт в очередь
        # и поднимается автоматически при первой отмене.
        alert = (
            f"Стол на игру #{game['id']} уже собран — вы в резерве, №{result.get('reserve_position')}. "
            "Освободится место — бот запишет вас и напишет."
        )
    else:
        role_label = texts.ROSTER_ROLES.get(result.get("role") or "", "").lower()
        suffix = f" ({role_label})" if role_label else ""
        alert = f"Записались на игру #{game['id']}{suffix} ✅"

    await _show_day(
        callback, state, api, token=token, game_type=game_type, role_kind=role_kind, alert=alert
    )


# --------------------------------------------------------- мои регистрации
def _is_past(item: dict) -> bool:
    """Игра уже началась. Сравнение обязано идти в клубной зоне: наивный
    datetime.now() в контейнере с UTC уводил границу на три часа, и вечерняя
    игра сразу после записи показывалась в «прошедших»."""
    return from_api_datetime(item["starts_at"]) <= now_local()


async def _my_items(api: ApiClient, tg_id: int, stage: str) -> list[dict]:
    items = await api.my_registrations(tg_id)
    visible = [item for item in items if _is_past(item) == (stage == "completed")]
    for item in visible:
        item["day_time"] = format_day_time(item["starts_at"])
        if item.get("is_reserve"):
            item["role"] = "reserve"
    return sorted(visible, key=lambda item: item["starts_at"], reverse=(stage == "completed"))


def _my_text(stage: str, items: list[dict]) -> str:
    title = "📋 Предстоящие игры" if stage == "active" else "📋 Прошедшие игры"
    if not items:
        empty = (
            "Вы пока никуда не записаны. Откройте «📝 Запись на игры» в меню, чтобы выбрать игру."
            if stage == "active"
            else "Сыгранных игр пока нет."
        )
        return f"{title}\n\n{empty}"
    return f"{title}\n\nНажмите на игру, чтобы увидеть состав и отменить запись."


@router.message(Command("my"))
async def my_registrations(message: Message, state: FSMContext, api: ApiClient) -> None:
    await consume_input(message)
    if not await require_profile(message, state, api):
        return
    await state.set_state(None)
    items = await _my_items(api, message.from_user.id, "active")
    await open_screen(message, state, _my_text("active", items), my_registrations_keyboard(items, "active"))


@router.callback_query(F.data.startswith("mr:list:"))
async def switch_stage(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    stage = callback.data.split(":")[2]
    if stage not in {"active", "completed"}:
        await callback.answer()
        return
    items = await _my_items(api, callback.from_user.id, stage)
    await edit_screen(callback, state, _my_text(stage, items), my_registrations_keyboard(items, stage))


@router.callback_query(F.data.startswith("mr:view:"))
async def view_registration(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    game_id = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id

    mine = await api.my_registrations(tg_id)
    own = next((item for item in mine if item["game_id"] == game_id), None)
    if own is None:
        await callback.answer("Вы не записаны на эту игру.", show_alert=True)
        return

    game = await api.get_session(tg_id, game_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    roster = await api.session_roster(tg_id, game_id)
    await edit_screen(
        callback,
        state,
        _roster_text(game, roster),
        my_registration_keyboard(
            game_id,
            is_reserve=bool(own.get("is_reserve")),
            # Прошедшую игру отменять нечего: запись уже стала историей.
            can_cancel=not _is_past(own),
        ),
    )


async def _notify_promoted(callback: CallbackQuery, game_id: int, result: dict) -> None:
    """Написать тому, кого подняли из резерва освободившимся местом.

    Мест освобождается два разных способа: отмена записи и уход игрока из-за
    стола в штаб. Оба возвращают одни и те же promoted_*-поля, и сообщение у
    них одно -- человеку всё равно, из-за чего освободилось место.
    """
    promoted = result.get("promoted_telegram_id")
    if not promoted:
        return
    try:
        await callback.bot.send_message(
            promoted,
            f"🎉 В игре #{game_id} освободилось место — вы переведены из резерва в основной состав!",
        )
    except Exception:
        # Человек мог заблокировать бота: своё место он всё равно получил,
        # ронять из-за этого чужое действие нельзя.
        logger.warning("Не удалось уведомить %s о переводе из резерва", promoted)


def _roster_text(game: dict, roster: dict) -> str:
    by_role: dict[str, list[dict]] = {"host": [], "judge": [], "player": []}
    for row in roster["registrations"]:
        by_role.setdefault(row["role"], []).append(row)

    lines = [
        f"Игра #{game['id']} · {texts.GAME_TYPES.get(game.get('game_type', ''), '')}",
        f"Когда: {format_day_time(game['starts_at'])}",
        f"Где: {game.get('location') or '—'}",
        "",
    ]
    for role in ("host", "judge", "player"):
        members = by_role.get(role, [])
        lines.append(f"{texts.ROSTER_ROLES[role]}:")
        if not members:
            lines.append("• пока никого")
        else:
            for index, member in enumerate(members, start=1):
                prefix = f"{index}." if role == "player" else "•"
                lines.append(f"{prefix} {member['nickname']}")
        lines.append("")

    reserves = roster.get("reserves") or []
    if reserves:
        lines.append("Резерв:")
        lines += [f"{index}. {item['nickname']}" for index, item in enumerate(reserves, start=1)]
    return "\n".join(lines).strip()


@router.callback_query(F.data.startswith("mr:cancel:"))
async def cancel_registration(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    game_id = int(callback.data.split(":")[2])
    try:
        result = await api.cancel_registration(callback.from_user.id, game_id)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if not result["ok"]:
        await callback.answer("Вы не записаны на эту игру.", show_alert=True)
        return

    await _notify_promoted(callback, game_id, result)

    items = await _my_items(api, callback.from_user.id, "active")
    await edit_screen(
        callback, state, _my_text("active", items), my_registrations_keyboard(items, "active"),
        alert="Запись отменена",
    )
