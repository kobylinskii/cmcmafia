"""Проверки чистой логики бота.

Сами диалоги проверяются вручную в Telegram, но то, что ниже, ломалось молча
и незаметно: нарезка игрового дня по часам, граница «прошедшая игра»,
развилка «игру пора подтвердить» и подтверждение доставки решений по заявкам.
Ничего из этого не требует ни Telegram, ни сети.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import texts
from app.api_client import LOCAL_TZ, now_local
from app.handlers.admin import _day_from_token, _hourly_starts, _needs_confirmation
from app.handlers.profile import _parse, _stats_line
from app.handlers.schedule import _is_past
from app.keyboards.inline import calendar_keyboard, hours_keyboard
from app.notifier import deliver_once


class FakeBot:
    def __init__(
        self,
        fail_for: set[int] | None = None,
        forbidden_for: set[int] | None = None,
        bad_request_for: dict[int, str] | None = None,
    ):
        self.sent: list[tuple[int, str]] = []
        self._fail_for = fail_for or set()
        self._forbidden_for = forbidden_for or set()
        self._bad_request_for = bad_request_for or {}

    async def send_message(self, chat_id: int, text: str) -> None:
        if chat_id in self._forbidden_for:
            from aiogram.exceptions import TelegramForbiddenError

            raise TelegramForbiddenError(method=None, message="bot was blocked by the user")
        if chat_id in self._bad_request_for:
            from aiogram.exceptions import TelegramBadRequest

            raise TelegramBadRequest(method=None, message=self._bad_request_for[chat_id])
        if chat_id in self._fail_for:
            raise RuntimeError("network is down")
        self.sent.append((chat_id, text))


class FakeApi:
    def __init__(self, queue: list[dict]):
        self.queue = queue
        self.acked: list[int] = []

    async def confirmation_notifications(self) -> list[dict]:
        return self.queue

    async def ack_confirmations(self, player_ids: list[int]) -> int:
        self.acked.extend(player_ids)
        return len(player_ids)


def _item(player_id: int, telegram_id: int, status: str = "confirmed", reason: str | None = None) -> dict:
    return {
        "player_id": player_id,
        "telegram_id": telegram_id,
        "nickname": f"Игрок{player_id}",
        "confirmation_status": status,
        "rejection_reason": reason,
    }


# ---------------------------------------------------------------- админка
def test_hourly_starts_are_left_closed():
    """Диапазон 18:00-21:00 -- это три игры, а не четыре: 21:00 уже конец."""
    assert _hourly_starts("26.08.2026", "18:00", "21:00") == [
        "26.08.2026 18:00",
        "26.08.2026 19:00",
        "26.08.2026 20:00",
    ]


def test_last_game_of_the_day_starts_before_midnight():
    """Верхняя граница сетки часов -- 24:00, и это игра в 23:00, а не в 24:00."""
    assert _hourly_starts("26.08.2026", "22:00", "24:00") == [
        "26.08.2026 22:00",
        "26.08.2026 23:00",
    ]


def test_day_token_round_trip():
    assert _day_from_token("26082026") == "26.08.2026"
    assert _day_from_token("2608") is None
    assert _day_from_token("не дата") is None


def _cells(markup) -> list[tuple[str, str]]:
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


def test_calendar_does_not_offer_past_days():
    """Игровой день задним числом не создают: на него нельзя записаться."""
    today = date(2026, 9, 15)
    cells = _cells(calendar_keyboard(year=2026, month=9, today=today, back_to="am:create"))
    picks = {text: data for text, data in cells if data.startswith("am:date:")}

    assert "14" not in picks, "прошедший день не должен быть кликабельным"
    assert picks["16"] == "am:date:16092026"
    # Сегодняшний день выбрать можно -- вечерняя игра сегодня остаётся игрой.
    assert "·15·" in picks


def test_calendar_does_not_flip_into_past_months():
    today = date(2026, 9, 15)
    current = _cells(calendar_keyboard(year=2026, month=9, today=today, back_to="am:create"))
    assert not any(data.startswith("am:cal:2026") and data < "am:cal:202609" for _, data in current)

    later = _cells(calendar_keyboard(year=2026, month=11, today=today, back_to="am:create"))
    assert ("◀️", "am:cal:202610") in later


def test_hours_keyboard_covers_the_whole_range():
    cells = _cells(hours_keyboard(action="to", first=19, last=24, back_to="am:pickfrom"))
    hours = [text for text, data in cells if data.startswith("am:to:")]
    assert hours == ["19:00", "20:00", "21:00", "22:00", "23:00", "24:00"]


@pytest.mark.parametrize(
    "status, hours_shift, expected",
    [
        ("scheduled", -3, True),
        # Игра ещё не началась -- подтверждать нечего.
        ("scheduled", 3, False),
        # Уже подтверждена: висеть в списке «состоялась ли?» ей незачем.
        ("played", -3, False),
        ("rated", -3, False),
    ],
)
def test_only_past_unconfirmed_games_ask_to_be_confirmed(status, hours_shift, expected):
    game = {
        "status": status,
        "starts_at": (now_local() + timedelta(hours=hours_shift)).isoformat(),
    }
    assert _needs_confirmation(game) is expected


# ---------------------------------------------------------------- профиль
@pytest.mark.parametrize(
    "field, raw, expected",
    [
        ("full_name", "  Иванов   Иван Иванович ", "Иванов Иван Иванович"),
        ("full_name", "Иванов Иван", None),
        ("full_name", "Ivanov Ivan Ivanovich", None),
        ("nickname", "Шериф", "Шериф"),
        ("nickname", "ше", None),
        ("nickname", "Шериф2000", None),
        ("age", "25", 25),
        ("age", "3", None),
        ("age", "двадцать", None),
        ("bio", "  ", None),
    ],
)
def test_profile_values_are_validated(field, raw, expected):
    assert _parse(field, raw) == expected


def test_stats_line_is_one_short_string():
    assert _stats_line(None) == "📊 Сыгранных игр пока нет."
    assert _stats_line({"total_games": 0}) == "📊 Сыгранных игр пока нет."
    line = _stats_line(
        {"total_games": 12, "wins": 7, "win_rate": 0.5833, "rating": 1043.27, "rank": 4}
    )
    assert line == "📊 игр 12 · побед 7 · 58% · рейтинг 1043 (#4)"


# --------------------------------------------------------------- расписание
def test_past_is_measured_in_club_time():
    """Наивный datetime.now() в контейнере с UTC сдвигал границу на три часа, и
    вечерняя игра сразу после записи показывалась как прошедшая."""
    soon = (now_local() + timedelta(hours=2)).astimezone(LOCAL_TZ)
    ago = (now_local() - timedelta(hours=2)).astimezone(LOCAL_TZ)
    assert _is_past({"starts_at": soon.isoformat()}) is False
    assert _is_past({"starts_at": ago.isoformat()}) is True


# ----------------------------------------------------------------- рассылка
@pytest.mark.asyncio
async def test_delivered_decisions_are_acked():
    api = FakeApi([_item(1, 100), _item(2, 200, "rejected", "ФИО не совпадает")])
    bot = FakeBot()

    assert await deliver_once(bot, api) == 2
    assert api.acked == [1, 2]
    assert "подтверждена" in bot.sent[0][1]
    assert "ФИО не совпадает" in bot.sent[1][1]


@pytest.mark.asyncio
async def test_temporary_failure_keeps_the_decision_in_the_queue():
    """Недоставленное решение не подтверждается: следующий проход повторит."""
    api = FakeApi([_item(1, 100), _item(2, 200)])
    bot = FakeBot(fail_for={200})

    assert await deliver_once(bot, api) == 1
    assert api.acked == [1]


@pytest.mark.asyncio
async def test_blocked_user_stops_clogging_the_queue():
    """Заблокировавшему бота доставить нельзя никогда -- иначе одна такая
    строка обрабатывалась бы до конца времён на каждом проходе."""
    api = FakeApi([_item(1, 100)])
    bot = FakeBot(forbidden_for={100})

    assert await deliver_once(bot, api) == 0
    assert api.acked == [1]


@pytest.mark.parametrize(
    "message",
    [
        "Telegram server says - Bad Request: chat not found",
        "Telegram server says - Bad Request: user is deactivated",
        "Telegram server says - Bad Request: bot was blocked by the user",
    ],
)
@pytest.mark.asyncio
async def test_unreachable_chat_reported_as_bad_request_stops_clogging_the_queue(message):
    """На несуществующий чат Telegram отвечает не 403, а 400 с текстом: пока
    такой ответ считался временным, строка висела в очереди вечно и валилась
    трейсбеком в логи на каждом проходе."""
    api = FakeApi([_item(1, 900002)])
    bot = FakeBot(bad_request_for={900002: message})

    assert await deliver_once(bot, api) == 0
    assert api.acked == [1]


@pytest.mark.asyncio
async def test_unexpected_bad_request_keeps_the_decision_in_the_queue():
    """400 не про недоступный чат -- ошибка в нашем же запросе: решение должно
    остаться в очереди и уйти после починки, а не потеряться молча."""
    api = FakeApi([_item(1, 100)])
    bot = FakeBot(bad_request_for={100: "Telegram server says - Bad Request: message text is empty"})

    assert await deliver_once(bot, api) == 0
    assert api.acked == []


# -------------------------------------------------------------------- тексты
def test_game_type_titles_cover_the_all_token():
    assert texts.game_type_title("funky") == "🎉 Фанки"
    assert texts.game_type_title(texts.ALL_GAMES) == texts.ALL_GAMES_LABEL
    assert texts.is_known_game_type(texts.ALL_GAMES)
    # Турнирные игры бот не заводит и не набирает -- см. ARCHITECTURE.md 7.7.
    assert not texts.is_known_game_type("tournament")


def test_preferred_roles_text():
    assert texts.preferred_roles_text(True, True) == "игрок, ведущий/судья"
    assert texts.preferred_roles_text(False, True) == "ведущий/судья"
    assert texts.preferred_roles_text(False, False) == "не выбраны"
