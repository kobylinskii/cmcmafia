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
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app import texts
from app.api_client import (
    ApiClient,
    ApiError,
    day_label,
    format_day,
    format_day_time,
    format_time,
    from_api_datetime,
    now_local,
)
from app.handlers.common import require_profile
from app.keyboards.inline import (
    DEEP_LINK_PREFIX,
    day_from_token,
    day_roster_keyboard,
    day_token,
    game_days_keyboard,
    game_slots_keyboard,
    game_types_keyboard,
    menu_only_keyboard,
    my_day_games_keyboard,
    my_days_keyboard,
    my_registration_keyboard,
    registration_role_keyboard,
)
from app.ui import clear_state, consume_input, edit_screen, open_screen

logger = logging.getLogger(__name__)

router = Router(name="schedule")

PICK_DAY = "📝 Запись на игры\n\nВыберите день:"
NO_GAMES = "Свободных игр для записи сейчас нет."
NO_ROLES = (
    "В профиле не отмечено ни одной роли. Откройте «Профиль» и выберите, "
    "за кого вы готовы играть."
)


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


class DayGone(Exception):
    """Игр этого дня не осталось: экран дня показывать нечего, надо вернуть
    человека к списку дней. Отдельным исключением, потому что случиться это
    может на любом шаге цепочки, а выход один."""


async def _day_screen(
    api: ApiClient,
    tg_id: int,
    *,
    token: str,
    game_type: str | None = None,
    role_kind: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Один проход по цепочке «день -> формат -> роль -> игры».

    Собран в одну функцию, а не в три обработчика: шаги пропускаются, когда
    выбирать не из чего, и после каждой записи экран перерисовывается с того
    же места. Тремя отдельными путями это разъезжалось бы на каждом шаге.

    Возвращает готовый экран, а не рисует его: тот же расчёт нужен и нажатию
    кнопки (правит текущее сообщение), и приходу по ссылке-deep-link из
    рассылки (присылает новое). Ошибки летят наверх: ApiError -- как есть,
    «нечего показывать» -- DayGone.
    """
    day = day_from_token(token)
    if day is None:
        raise ApiError(400, "Некорректная дата.")

    games = [_with_time(g) for g in await api.list_open_sessions(tg_id, day=day)]
    if not games:
        raise DayGone

    # Шаг 1: формат. Спрашиваем, только если в дне есть и фанки, и обучающие.
    present = sorted({g["game_type"] for g in games})
    if game_type is None:
        if len(present) > 1:
            return (
                f"📅 {day_label(day)}\n\nКакие игры показать?",
                game_types_keyboard(token, present),
            )
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
        raise ApiError(404, "Профиль не найден, начните с /start.")
    can_play, can_staff = bool(user.get("can_play")), bool(user.get("can_staff"))
    if not (can_play or can_staff):
        raise ApiError(400, NO_ROLES)
    both_roles = can_play and can_staff

    if role_kind is None:
        if both_roles:
            return (
                f"📅 {day_label(day)} · {texts.game_type_title(game_type)}\n\n"
                "В какой роли записываемся?",
                registration_role_keyboard(
                    token, game_type, can_play=True, can_staff=True, back_to=after_type
                ),
            )
        role_kind = "player" if can_play else "staff"
    after_role = f"sg:cat:{token}:{game_type}" if both_roles else after_type

    return (
        f"📅 {day_label(day)} · {texts.game_type_title(game_type)} · "
        f"{texts.REGISTRATION_ROLES.get(role_kind, '')}\n\n"
        "Нажмите на игру, чтобы записаться, на свою (✅) — чтобы отменить запись.\n"
        "Собранный стол помечен «в резерв» — запись на него ставит в очередь.",
        game_slots_keyboard(
            token=token, game_type=game_type, role_kind=role_kind, games=games, back_to=after_role
        ),
    )


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
    tg_id = callback.from_user.id
    try:
        text, keyboard = await _day_screen(
            api, tg_id, token=token, game_type=game_type, role_kind=role_kind
        )
    except DayGone:
        await _days_screen(
            callback, state, api, tg_id, edit=True, alert="На этот день игр не осталось"
        )
        return
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await edit_screen(callback, state, text, keyboard, alert=alert)


# Приход по кнопке-ссылке из рассылки: `/start day19092026`. Регистрируется в
# этом роутере, а не в common: schedule подключается раньше, и более узкий
# фильтр забирает такой /start себе, оставляя обычный common'у.
@router.message(CommandStart(deep_link=True, magic=F.args.startswith(DEEP_LINK_PREFIX)))
async def start_on_day(
    message: Message, state: FSMContext, api: ApiClient, command: CommandObject
) -> None:
    await clear_state(state)
    await consume_input(message)
    if not await require_profile(message, state, api):
        return
    token = (command.args or "").removeprefix(DEEP_LINK_PREFIX)
    try:
        text, keyboard = await _day_screen(api, message.from_user.id, token=token)
    except DayGone:
        await _days_screen(message, state, api, message.from_user.id, edit=False)
        return
    except ApiError as exc:
        await open_screen(message, state, exc.message, menu_only_keyboard())
        return
    await open_screen(message, state, text, keyboard)


@router.callback_query(F.data.startswith("sg:day:"))
async def pick_day(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await _show_day(callback, state, api, token=callback.data.split(":")[2])


@router.callback_query(F.data.startswith("sg:who:"))
async def show_day_roster(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    """Состав всех игр дня одним экраном.

    Раньше состав был виден только у своей игры, из «Мои регистрации», -- то
    есть узнать, кто сегодня придёт, мог лишь тот, кто уже записался. Вопрос
    же ровно обратный: люди смотрят состав, чтобы решить, идти ли вообще.
    """
    # Хвост «:формат:роль» дописан не всегда: такая кнопка могла остаться в
    # чате с прошлой версии, и тогда «Назад» ведёт в начало цепочки дня.
    parts = callback.data.split(":")
    token = parts[2]
    back_to = (
        f"sg:role:{token}:{parts[3]}:{parts[4]}" if len(parts) == 5 else f"sg:day:{token}"
    )
    day = day_from_token(token)
    if day is None:
        await callback.answer("Некорректная дата.", show_alert=True)
        return
    tg_id = callback.from_user.id
    games = await api.list_open_sessions(tg_id, day=day)
    if not games:
        await _days_screen(
            callback, state, api, tg_id, edit=True, alert="На этот день игр не осталось"
        )
        return

    rosters = [await api.session_roster(tg_id, game["id"]) for game in games]
    await edit_screen(
        callback,
        state,
        _day_roster_text(day, rosters),
        day_roster_keyboard(back_to),
    )


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


async def _cancel_from_slots(
    callback: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    *,
    game: dict,
    token: str,
    game_type: str,
    role_kind: str,
) -> None:
    """Повторное нажатие на свою строку -- отмена записи.

    Отменяет и резерв: на бэкенде это одна ручка (unregister смотрит и в
    записи, и в очередь), и человеку разница тем более не важна.
    """
    try:
        result = await api.cancel_registration(callback.from_user.id, game["id"])
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if not result["ok"]:
        await callback.answer("Вы не записаны на эту игру.", show_alert=True)
        return

    # Освободившееся место могло поднять первого из очереди -- ему надо
    # написать так же, как при отмене из «Мои регистрации».
    await _notify_promoted(callback, game["id"], result)
    await _show_day(
        callback,
        state,
        api,
        token=token,
        game_type=game_type,
        role_kind=role_kind,
        alert=f"Запись на игру #{game['id']} отменена",
    )


@router.callback_query(F.data.startswith("sg:game:"))
async def register_for_game(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    _, _, token, game_type, role_kind, raw_id = callback.data.split(":")
    tg_id = callback.from_user.id
    game = await api.get_session(tg_id, int(raw_id))
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    # Своя запись осталась в списке с галочкой, и та же строка её снимает:
    # запись и отмена -- одно действие с двумя исходами, и второе место для
    # отмены («Мои регистрации») нужно только тем, кто пришёл туда за составом.
    if game.get("my_role"):
        await _cancel_from_slots(
            callback, state, api, game=game, token=token, game_type=game_type, role_kind=role_kind
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
# Раздел устроен так же, как запись: сначала день, потом игры этого дня.
# Вкладок «Предстоящие»/«Прошедшие» больше нет -- прошедшие записи сюда не
# попадают вовсе: отменять в них нечего, а сыгранное видно в профиле и на
# сайте.
MY_EMPTY = (
    "📋 Мои регистрации\n\n"
    "Вы пока никуда не записаны. Откройте «📝 Запись на игры» в меню, чтобы выбрать игру."
)
MY_DAYS = "📋 Мои регистрации\n\nВыберите день:"


def _is_past(item: dict) -> bool:
    """Игра уже началась. Сравнение обязано идти в клубной зоне: наивный
    datetime.now() в контейнере с UTC уводил границу на три часа, и вечерняя
    игра сразу после записи показывалась в «прошедших»."""
    return from_api_datetime(item["starts_at"]) <= now_local()


async def _my_items(api: ApiClient, tg_id: int, *, day: str | None = None) -> list[dict]:
    """Мои предстоящие записи, при желании -- только за один день."""
    items = [item for item in await api.my_registrations(tg_id) if not _is_past(item)]
    for item in items:
        item["day"] = format_day(item["starts_at"])
        item["time"] = format_time(item["starts_at"])
        if item.get("is_reserve"):
            item["role"] = "reserve"
    if day is not None:
        items = [item for item in items if item["day"] == day]
    return sorted(items, key=lambda item: item["starts_at"])


def _my_days(items: list[dict]) -> list[tuple[str, int]]:
    days: dict[str, int] = {}
    for item in items:
        days[item["day"]] = days.get(item["day"], 0) + 1
    return list(days.items())


async def _my_days_screen(
    callback_or_message, state, api: ApiClient, tg_id: int, *, edit: bool, alert: str | None = None
) -> None:
    items = await _my_items(api, tg_id)
    text = MY_DAYS if items else MY_EMPTY
    keyboard = my_days_keyboard(_my_days(items))
    if edit:
        await edit_screen(callback_or_message, state, text, keyboard, alert=alert)
    else:
        await open_screen(callback_or_message, state, text, keyboard)


@router.message(Command("my"))
async def my_registrations(message: Message, state: FSMContext, api: ApiClient) -> None:
    await consume_input(message)
    if not await require_profile(message, state, api):
        return
    await state.set_state(None)
    await _my_days_screen(message, state, api, message.from_user.id, edit=False)


# "mr:list:*" -- вкладки прошлой версии раздела. Такие клавиатуры висят в
# чатах, и нажатие на них должно вести в новый первый экран, а не крутить
# часики.
@router.callback_query((F.data == "mr:days") | F.data.startswith("mr:list:"))
async def show_my_days(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(None)
    await _my_days_screen(callback, state, api, callback.from_user.id, edit=True)


@router.callback_query(F.data.startswith("mr:day:"))
async def show_my_day(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    day = day_from_token(callback.data.split(":")[2])
    if day is None:
        await callback.answer("Некорректная дата.", show_alert=True)
        return
    await _my_day_screen(callback, state, api, day=day)


async def _my_day_screen(
    callback: CallbackQuery, state: FSMContext, api: ApiClient, *, day: str,
    alert: str | None = None,
) -> None:
    """Мои игры одного дня. Зовётся и кнопкой дня, и отменой записи."""
    items = await _my_items(api, callback.from_user.id, day=day)
    if not items:
        await _my_days_screen(
            callback, state, api, callback.from_user.id, edit=True,
            alert="На этот день у вас записей не осталось",
        )
        return
    await edit_screen(
        callback,
        state,
        f"📋 {day_label(day)}\n\nНажмите на игру, чтобы увидеть состав и отменить запись.",
        my_day_games_keyboard(items),
        alert=alert,
    )


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
    # День берётся из самой игры: в callback_data он не нужен, а «Назад»
    # обязан вести в тот же день, а не в общий список.
    token = day_token(format_day(game["starts_at"]))
    await edit_screen(
        callback,
        state,
        _roster_text(game, roster),
        my_registration_keyboard(
            game_id,
            is_reserve=bool(own.get("is_reserve")),
            # Прошедшую игру отменять нечего: запись уже стала историей.
            can_cancel=not _is_past(own),
            back_to=f"mr:day:{token}",
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


# Ведущий и судьи -- один штаб на три места, и делить его на два раздела
# незачем: набирают их вместе, и вопрос всегда один -- хватает ли людей на
# стол, а не кто из них сегодня судит. Так же их считает и строка игры в
# списке (keyboards.inline._slot_label: hosts + judges из трёх).
ROSTER_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Ведущие/судьи", ("host", "judge")),
    ("Игроки", ("player",)),
)


def _roster_sections(people: dict[str, list[str]], reserves: list[str]) -> list[str]:
    """Разделы состава -- общие у одной игры и у целого дня.

    Номер в списке отвечает на главный вопрос обоих разделов: сколько уже
    набралось -- из трёх мест в штабе и из десяти за столом.
    """
    lines: list[str] = []
    for title, roles in ROSTER_GROUPS:
        members = [name for role in roles for name in people.get(role) or []]
        lines.append(f"{title} ({len(members)}):" if members else f"{title}: пока никого")
        lines += [f"{index}. {name}" for index, name in enumerate(members, start=1)]
        lines.append("")
    if reserves:
        lines.append(f"Резерв ({len(reserves)}):")
        lines += [f"{index}. {name}" for index, name in enumerate(reserves, start=1)]
    return lines


def _day_roster_text(day: str, rosters: list[dict]) -> str:
    """Состав дня одним списком, а не столбиком составов по играм.

    Клуб играет вечер целиком: человек смотрит, кто сегодня придёт, а не кто
    сядет за какой из трёх столов. Разбивка по играм превращала экран в
    простыню, в которой одни и те же люди повторялись по несколько раз --
    записанный на две игры подряд считается один раз и здесь.
    """
    people: dict[str, list[str]] = {}
    reserves: list[str] = []
    for roster in rosters:
        for row in roster.get("registrations") or []:
            group = people.setdefault(row["role"], [])
            if row["nickname"] not in group:
                group.append(row["nickname"])
        for row in roster.get("reserves") or []:
            if row["nickname"] not in reserves:
                reserves.append(row["nickname"])

    lines = [f"👥 Кто записан — {day_label(day)}", ""]
    lines += _roster_sections(people, reserves)
    return "\n".join(lines).strip()


def _roster_text(game: dict, roster: dict) -> str:
    """Состав одной игры -- карточка из «Мои регистрации». Разделы те же, что
    и у дня: штаб одним куском, потом стол, потом очередь."""
    people: dict[str, list[str]] = {}
    for row in roster["registrations"]:
        people.setdefault(row["role"], []).append(row["nickname"])

    lines = [
        f"Игра #{game['id']} · {texts.GAME_TYPES.get(game.get('game_type', ''), '')}",
        f"Когда: {format_day_time(game['starts_at'])}",
        f"Где: {game.get('location') or '—'}",
        "",
    ]
    lines += _roster_sections(people, [row["nickname"] for row in roster.get("reserves") or []])
    return "\n".join(lines).strip()


@router.callback_query(F.data.startswith("mr:cancel:"))
async def cancel_registration(callback: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    game_id = int(callback.data.split(":")[2])
    tg_id = callback.from_user.id
    game = await api.get_session(tg_id, game_id)
    try:
        result = await api.cancel_registration(tg_id, game_id)
    except ApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if not result["ok"]:
        await callback.answer("Вы не записаны на эту игру.", show_alert=True)
        return

    await _notify_promoted(callback, game_id, result)

    # Возвращаемся в тот же день, пока в нём осталась хоть одна запись:
    # чаще всего человек отменяет одну игру из двух подряд.
    day = format_day(game["starts_at"]) if game else None
    if day is not None and await _my_items(api, tg_id, day=day):
        await _my_day_screen(
            callback, state, api, day=day, alert="Запись отменена"
        )
        return
    await _my_days_screen(callback, state, api, tg_id, edit=True, alert="Запись отменена")
