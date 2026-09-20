"""Рассылка по одному игровому дню: «собрать за стол» и «напомнить».

Автоматического напоминания за три часа больше нет -- обе рассылки запускает
админ кнопкой в боте, а бэкенд отвечает на те же два вопроса, что и для
недельного анонса: какие игры в этот день и кому писать.

Аудитории ровно две и они дополняют друг друга: `absent` -- клуб без тех, кто
на день уже записан, `registered` -- только они. Проверяется именно это
разделение: перепутанная аудитория рассылает «приходите записываться» тем, кто
уже идёт, и молчит тем, ради кого кнопку нажали.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.timeutil import club_day
from tests.conftest import (
    BOT_HEADERS,
    make_bot_admin,
    make_session,
    register_bot_player,
    set_game_time,
)

ADMIN_TG = 7001


@pytest.fixture
def club(admin):
    """Клуб с админом бота: ручки рассылки требуют именно его прав."""
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="Организатор бота", slug="bot-organizer")
    return client, headers


def _broadcast(client, day: str, audience: str) -> dict:
    resp = client.get(
        f"/api/bot/admin/broadcast/day?telegram_id={ADMIN_TG}&day={day}&audience={audience}",
        headers=BOT_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _recipients(payload: dict) -> set[int]:
    return {item["telegram_id"] for item in payload["recipients"]}


def _sign_up(client, game_id: int, telegram_id: int) -> None:
    resp = client.post(
        f"/api/bot/sessions/{game_id}/register?telegram_id={telegram_id}",
        headers=BOT_HEADERS,
        json={"telegram_id": telegram_id, "role_kind": "player"},
    )
    assert resp.status_code == 200, resp.text


def _in(hours: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _game_in(client, headers, hours: float) -> tuple[int, str]:
    """Игра через `hours` часов и её клубный день.

    Время двигается в БД, а не задаётся при создании: планировщик сессий в
    прошлом не создаёт, а «сегодня» у теста обязано считаться от момента
    прогона -- иначе тест зависел бы от даты запуска.
    """
    game = make_session(client, headers, starts_at="2030-06-01T15:00:00Z")
    starts_at = _in(hours)
    set_game_time(game, starts_at=starts_at)
    return game, club_day(starts_at)


def test_gathering_skips_everyone_already_signed_up_for_that_day(club):
    """Смысл кнопки -- добрать людей за стол, а не написать тем, кто уже идёт."""
    client, headers = club
    register_bot_player(client, 7101, "Записавшийся")
    register_bot_player(client, 7102, "Свободный")
    game, day = _game_in(client, headers, 5)
    _sign_up(client, game, 7101)

    payload = _broadcast(client, day, "absent")
    assert 7102 in _recipients(payload)
    assert 7101 not in _recipients(payload)
    assert [g["id"] for g in payload["games"]] == [game]


def test_reminder_goes_to_the_signed_up_including_reserve(club):
    client, headers = club
    register_bot_player(client, 7201, "Основной")
    register_bot_player(client, 7202, "Запасной")
    register_bot_player(client, 7203, "Мимо")
    game, day = _game_in(client, headers, 5)
    _sign_up(client, game, 7201)
    resp = client.post(
        f"/api/bot/sessions/{game}/reserve?telegram_id=7202",
        headers=BOT_HEADERS,
        json={"telegram_id": 7202},
    )
    assert resp.status_code == 200, resp.text

    assert _recipients(_broadcast(client, day, "registered")) == {7201, 7202}


def test_reminder_keeps_games_with_registration_already_closed(club):
    """Напоминание уходит в день игры, когда запись давно закрыта: без этого
    сообщение «сегодня игры» пришло бы с пустым списком."""
    client, headers = club
    register_bot_player(client, 7301, "Игрок")
    game, day = _game_in(client, headers, 2)
    _sign_up(client, game, 7301)
    set_game_time(game, registration_until=_in(-1))

    reminder = _broadcast(client, day, "registered")
    assert [g["id"] for g in reminder["games"]] == [game]
    assert _recipients(reminder) == {7301}

    # А звать записываться на игру с закрытой записью нечем.
    assert _broadcast(client, day, "absent")["games"] == []


def test_other_days_do_not_leak_into_the_broadcast(club):
    client, headers = club
    register_bot_player(client, 7401, "Игрок")
    today, day = _game_in(client, headers, 3)
    other, other_day = _game_in(client, headers, 50)
    _sign_up(client, other, 7401)
    assert other_day != day

    payload = _broadcast(client, day, "absent")
    assert [g["id"] for g in payload["games"]] == [today]
    # Запись на другой день не выводит человека из аудитории этого дня.
    assert 7401 in _recipients(payload)


def test_unknown_audience_is_rejected(club):
    client, _ = club
    resp = client.get(
        f"/api/bot/admin/broadcast/day?telegram_id={ADMIN_TG}&day=01.06.2030&audience=everyone",
        headers=BOT_HEADERS,
    )
    assert resp.status_code == 422, resp.text


def test_reminder_narrows_down_to_the_games_that_will_actually_happen(club):
    """Админ отмечает в напоминании, какие игры сегодня состоятся: писать
    «сегодня играем» тому, чья игра отменена, было бы враньём."""
    client, headers = club
    register_bot_player(client, 7501, "Ранний")
    register_bot_player(client, 7502, "Поздний")
    first, day = _game_in(client, headers, 3)
    second, same_day = _game_in(client, headers, 5)
    assert same_day == day
    _sign_up(client, first, 7501)
    _sign_up(client, second, 7502)

    resp = client.get(
        f"/api/bot/admin/broadcast/day?telegram_id={ADMIN_TG}&day={day}"
        f"&audience=registered&game_ids={first}",
        headers=BOT_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert [g["id"] for g in payload["games"]] == [first]
    assert _recipients(payload) == {7501}


def test_broken_game_ids_are_rejected(club):
    client, _ = club
    resp = client.get(
        f"/api/bot/admin/broadcast/day?telegram_id={ADMIN_TG}&day=01.06.2030"
        "&audience=registered&game_ids=почти-id",
        headers=BOT_HEADERS,
    )
    assert resp.status_code == 422, resp.text
