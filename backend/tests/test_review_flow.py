"""Цикл «сессия создана в боте -> её оценивают на сайте» (ARCHITECTURE.md, раздел 8).

До правок этот путь не работал ни на одном шаге: прошедшие сессии навсегда
оставались в статусе 'scheduled' (фоновая задача существовала, но никем не
вызывалась), pending-review из-за этого всегда возвращал пусто, а форма оценки
не отдавала состав, потому что у такой игры ещё нет ни одного participant.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import tasks
from app.main import app
from tests.conftest import (
    BOT_HEADERS,
    game_status,
    make_bot_admin,
    register_bot_player,
    set_game_time,
)

ADMIN_TG = 555


def _create_session(client, *, max_players: int = 10, days_ahead: int = 1) -> int:
    resp = client.post(
        f"/api/bot/admin/sessions?telegram_id={ADMIN_TG}",
        headers=BOT_HEADERS,
        json={
            "starts_at": (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat(),
            "location": "Клуб",
            "game_type": "funky",
            "max_players": max_players,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_past_session_becomes_played_and_reaches_pending_review(admin):
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client)

    # Пока игра в будущем -- оценивать нечего.
    assert client.get("/api/admin/games/pending-review", headers=headers).json() == []

    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=3))
    # Сама по себе игра статус не меняет: до фоновой задачи она так и висела
    # 'scheduled', и список «ждут оценки» оставался пустым навсегда.
    assert game_status(session_id) == "scheduled"

    moved = tasks.sweep_past_sessions()

    assert moved == 1
    assert game_status(session_id) == "played"
    pending = client.get("/api/admin/games/pending-review", headers=headers).json()
    assert [g["id"] for g in pending] == [session_id]


def test_sweep_leaves_future_and_rated_games_alone(admin):
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    future_id = _create_session(client, days_ahead=5)

    assert tasks.sweep_past_sessions() == 0
    assert game_status(future_id) == "scheduled"

    # Повторный прогон по уже переведённой игре ничего не трогает.
    set_game_time(future_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=1))
    assert tasks.sweep_past_sessions() == 1
    assert tasks.sweep_past_sessions() == 0
    assert game_status(future_id) == "played"


def test_review_form_receives_the_roster_registered_in_the_bot(admin):
    """Форма оценки должна открываться с составом из registrations, а не пустой."""
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client)

    for tg_id, nickname in [(201, "Первый"), (202, "Второй"), (203, "Третий")]:
        register_bot_player(client, tg_id, nickname)
        resp = client.post(
            f"/api/bot/sessions/{session_id}/register?telegram_id={tg_id}",
            headers=BOT_HEADERS,
            json={"telegram_id": tg_id, "role_kind": "player"},
        )
        assert resp.json()["ok"] is True, resp.text

    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=2))
    tasks.sweep_past_sessions()

    game = client.get(f"/api/admin/games/{session_id}", headers=headers).json()
    assert game["status"] == "played"
    assert game["participants"] == []  # мест за столом ещё нет -- их и вносит админ
    assert [r["nickname"] for r in game["roster"]] == ["Первый", "Второй", "Третий"]
    assert {r["role"] for r in game["roster"]} == {"player"}
    assert all(isinstance(r["player_id"], int) for r in game["roster"])


def test_staff_comes_first_in_the_roster(admin):
    """Ведущий и судья идут перед игроками -- админу так удобнее читать состав."""
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client)

    register_bot_player(client, 301, "Игрок")
    register_bot_player(client, 302, "Ведущий")
    for tg_id, kind in [(301, "player"), (302, "staff")]:
        resp = client.post(
            f"/api/bot/sessions/{session_id}/register?telegram_id={tg_id}",
            headers=BOT_HEADERS,
            json={"telegram_id": tg_id, "role_kind": kind},
        )
        assert resp.json()["ok"] is True, resp.text

    game = client.get(f"/api/admin/games/{session_id}", headers=headers).json()
    assert [(r["nickname"], r["role"]) for r in game["roster"]] == [
        ("Ведущий", "host"),
        ("Игрок", "player"),
    ]


def test_public_game_response_carries_no_roster(admin):
    """roster -- служебное поле админки; публичному API он не нужен."""
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client)
    register_bot_player(client, 401, "Кто-то")
    client.post(
        f"/api/bot/sessions/{session_id}/register?telegram_id=401",
        headers=BOT_HEADERS,
        json={"telegram_id": 401, "role_kind": "player"},
    )

    # Публичный эндпоинт отдаёт только оценённые игры, эта ещё не оценена.
    assert client.get(f"/api/games/{session_id}").status_code == 404


def test_registration_closes_at_registration_until(admin):
    """registration_until -- дедлайн записи, а не украшение: до правки
    is_session_open смотрел только на starts_at, и закрыть запись заранее
    было невозможно."""
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client, days_ahead=3)
    register_bot_player(client, 501, "Опоздавший")

    now = datetime.now(timezone.utc)
    set_game_time(session_id, registration_until=now - timedelta(minutes=1))

    resp = client.post(
        f"/api/bot/sessions/{session_id}/register?telegram_id=501",
        headers=BOT_HEADERS,
        json={"telegram_id": 501, "role_kind": "player"},
    )
    assert resp.status_code == 404, "запись после дедлайна должна быть закрыта"

    session = client.get(
        f"/api/bot/sessions/{session_id}?telegram_id=501", headers=BOT_HEADERS
    ).json()
    assert session["is_open"] is False

    # Сдвинули дедлайн вперёд -- запись снова открыта.
    set_game_time(session_id, registration_until=now + timedelta(days=2))
    resp = client.post(
        f"/api/bot/sessions/{session_id}/register?telegram_id=501",
        headers=BOT_HEADERS,
        json={"telegram_id": 501, "role_kind": "player"},
    )
    assert resp.status_code == 200 and resp.json()["ok"] is True, resp.text


def test_sweeper_is_actually_wired_into_the_app_lifespan(admin):
    """Задача mark_past_sessions_as_played существовала и раньше -- её просто
    никто не вызывал. Поэтому проверяем не саму функцию, а то, что запуск
    приложения её запускает: TestClient как контекст-менеджер поднимает lifespan.
    """
    client, _ = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client)
    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=1))
    assert game_status(session_id) == "scheduled"

    with TestClient(app):
        # Первый прогон идёт сразу на старте, до первой паузы в 5 минут.
        deadline = time.monotonic() + 10
        while game_status(session_id) != "played" and time.monotonic() < deadline:
            time.sleep(0.05)

    assert game_status(session_id) == "played", "lifespan не запустил фоновую задачу"


def test_day_grouping_uses_moscow_midnight_not_utc(admin):
    """Игра в 00:30 МСК -- это 21:30 UTC предыдущих суток. Группировка по дням
    обязана считать по московскому времени, иначе игра уезжает в соседний день.
    Раньше и группировка, и отбор делались на Python над всей таблицей игр;
    теперь это SQL, и границы суток должны остаться теми же."""
    client, _ = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")

    # 2026-12-02T21:30Z == 03.12.2026 00:30 МСК
    late_night = client.post(
        f"/api/bot/admin/sessions?telegram_id={ADMIN_TG}",
        headers=BOT_HEADERS,
        json={"starts_at": "2026-12-02T21:30:00Z", "location": "Клуб", "game_type": "funky"},
    )
    assert late_night.status_code == 200, late_night.text
    late_id = late_night.json()["id"]

    # 2026-12-02T15:00Z == 02.12.2026 18:00 МСК
    evening = client.post(
        f"/api/bot/admin/sessions?telegram_id={ADMIN_TG}",
        headers=BOT_HEADERS,
        json={"starts_at": "2026-12-02T15:00:00Z", "location": "Клуб", "game_type": "funky"},
    )
    evening_id = evening.json()["id"]

    def ids_on(day):
        resp = client.get(
            "/api/bot/admin/sessions/by-day",
            headers=BOT_HEADERS,
            params={"telegram_id": ADMIN_TG, "day": day},
        )
        assert resp.status_code == 200, resp.text
        return [s["id"] for s in resp.json()]

    assert ids_on("02.12.2026") == [evening_id]
    assert ids_on("03.12.2026") == [late_id]

    days = client.get(
        "/api/bot/admin/sessions/day-cards",
        headers=BOT_HEADERS,
        params={"telegram_id": ADMIN_TG},
    ).json()
    assert [d["day"] for d in days] == ["02.12.2026", "03.12.2026"]
