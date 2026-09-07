"""Напоминание «сегодня игры» за три часа до первой игры дня.

Очередь устроена как остальные рассылки бота: бэкенд копит, бот забирает
опросом, рассылает и подтверждает ack'ом. Проверяется окно (раньше трёх часов
не зовём, после начала -- поздно), склейка дня в одно напоминание и то, что
до ack'а строка из очереди не уходит.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import BOT_HEADERS, make_session, register_bot_player, set_game_time


def _queue(client) -> list[dict]:
    resp = client.get("/api/bot/day-reminders", headers=BOT_HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _sign_up(client, game_id: int, telegram_id: int, role_kind: str = "player") -> None:
    resp = client.post(
        f"/api/bot/sessions/{game_id}/register?telegram_id={telegram_id}",
        headers=BOT_HEADERS,
        json={"telegram_id": telegram_id, "role_kind": role_kind},
    )
    assert resp.status_code == 200, resp.text


def _in(hours: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def test_reminder_appears_only_inside_the_three_hour_window(admin):
    client, headers = admin
    register_bot_player(client, 6001, "Клык")
    game = make_session(client, headers, starts_at="2030-06-01T15:00:00Z")
    _sign_up(client, game, 6001)

    # Игра далеко -- напоминать рано.
    assert _queue(client) == []

    set_game_time(game, starts_at=_in(2))
    queue = _queue(client)
    assert len(queue) == 1
    assert queue[0]["recipients"] == [6001]
    assert queue[0]["marker_game_id"] == game

    # Игра уже началась -- напоминать поздно.
    set_game_time(game, starts_at=_in(-0.5))
    assert _queue(client) == []


def test_one_reminder_per_day_covers_all_its_games(admin):
    """Записанный на две игры одного дня получает одно напоминание, а не два."""
    client, headers = admin
    register_bot_player(client, 6002, "Тень")
    first = make_session(client, headers, starts_at="2030-06-01T15:00:00Z")
    second = make_session(client, headers, starts_at="2030-06-01T18:00:00Z")
    _sign_up(client, first, 6002)
    _sign_up(client, second, 6002)

    set_game_time(first, starts_at=_in(2))
    set_game_time(second, starts_at=_in(4))

    queue = _queue(client)
    assert len(queue) == 1
    assert queue[0]["marker_game_id"] == first
    assert len(queue[0]["games"]) == 2
    assert queue[0]["recipients"] == [6002]


def test_reserve_is_reminded_too(admin):
    client, headers = admin
    register_bot_player(client, 6003, "Запасной")
    game = make_session(client, headers, starts_at="2030-06-01T15:00:00Z")
    resp = client.post(
        f"/api/bot/sessions/{game}/reserve?telegram_id=6003",
        headers=BOT_HEADERS,
        json={"telegram_id": 6003},
    )
    assert resp.status_code == 200, resp.text

    set_game_time(game, starts_at=_in(1))
    assert _queue(client)[0]["recipients"] == [6003]


def test_reminder_clears_from_the_queue_only_on_ack(admin):
    client, headers = admin
    register_bot_player(client, 6004, "Сигнал")
    game = make_session(client, headers, starts_at="2030-06-01T15:00:00Z")
    _sign_up(client, game, 6004)
    set_game_time(game, starts_at=_in(1))

    # Повторный опрос до ack'а всё ещё отдаёт день: сообщение могло не уйти.
    assert len(_queue(client)) == 1
    assert len(_queue(client)) == 1

    ack = client.post(
        "/api/bot/day-reminders/ack", headers=BOT_HEADERS, json={"game_ids": [game]}
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["marked"] == 1
    assert _queue(client) == []


def test_day_without_a_single_signup_is_not_reminded(admin):
    client, headers = admin
    register_bot_player(client, 6005, "Зритель")
    game = make_session(client, headers, starts_at="2030-06-01T15:00:00Z")
    set_game_time(game, starts_at=_in(1))
    assert _queue(client) == []
