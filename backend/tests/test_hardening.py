"""Нестандартные ситуации, найденные финальным аудитом.

Каждый тест здесь падал до соответствующей правки -- это не проверка «оно
вообще работает», а фиксация конкретного разобранного случая, чтобы он не
вернулся.
"""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal
from app.main import app
from app.rate_limit import limiter
from app.services import player_service

from tests.conftest import (
    BOT_HEADERS,
    make_session,
    register_bot_player,
    reset_state,
    set_game_max_players,
    set_game_time,
)

# Больше, чем влезает в PostgreSQL integer: такого id не бывает, а запрос с
# ним доезжал до драйвера и падал «integer out of range» -- 500 вместо 404.
OVERFLOW_ID = 2**31
BIGINT_OVERFLOW = 2**63 + 1


def test_public_game_id_beyond_int_range_is_rejected_not_crashed(clean_db) -> None:
    client = TestClient(app)
    for value in (OVERFLOW_ID, BIGINT_OVERFLOW):
        resp = client.get(f"/api/games/{value}")
        assert resp.status_code == 422, f"{value}: {resp.status_code} {resp.text[:200]}"


def test_admin_and_bot_ids_beyond_int_range_are_rejected(admin) -> None:
    client, headers = admin
    for method, url in (
        ("GET", f"/api/admin/games/{OVERFLOW_ID}"),
        ("GET", f"/api/admin/players/{OVERFLOW_ID}"),
        ("GET", f"/api/admin/tournaments/{OVERFLOW_ID}"),
        ("GET", f"/api/admin/schedule/sessions/{OVERFLOW_ID}"),
    ):
        resp = client.request(method, url, headers=headers)
        assert resp.status_code == 422, f"{url}: {resp.status_code}"

    # Реальный игрок бота: иначе раньше проверки пути сработает get_bot_actor
    # и ответит своей 404 «игрок не найден», а проверяем мы не её.
    register_bot_player(client, 7001, "Гость")
    limiter.reset()
    resp = client.get(
        f"/api/bot/sessions/{OVERFLOW_ID}", headers=BOT_HEADERS, params={"telegram_id": 7001}
    )
    assert resp.status_code == 422
    # telegram_id живёт в BIGINT -- у него своя граница, шире обычного ключа.
    resp = client.get(
        "/api/bot/players/me", headers=BOT_HEADERS, params={"telegram_id": BIGINT_OVERFLOW}
    )
    assert resp.status_code == 422


def test_concurrent_signups_never_overfill_the_table(admin) -> None:
    """Стол из двух мест на восемь одновременных нажатий.

    Проверка «есть место» и вставка записи -- два запроса; без блокировки
    строки игры между ними влезал такой же параллельный запрос, и за стол
    садилось четверо. Остальные обязаны уйти в резерв, а не потеряться.
    """
    client, headers = admin
    session_id = make_session(client, headers, starts_at="2030-01-01T18:00:00Z")
    set_game_max_players(session_id, 2)
    telegram_ids = list(range(9001, 9009))
    for tg in telegram_ids:
        register_bot_player(client, tg, f"Гонщик{tg}")
    limiter.reset()

    def join(tg: int) -> None:
        # Свой клиент на поток: TestClient держит куки и состояние сессии.
        TestClient(app).post(
            f"/api/bot/sessions/{session_id}/register",
            headers=BOT_HEADERS,
            json={"telegram_id": tg, "role_kind": "player"},
        )

    threads = [threading.Thread(target=join, args=(tg,)) for tg in telegram_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    db = SessionLocal()
    try:
        seated = (
            db.query(models.Registration)
            .filter(models.Registration.game_id == session_id, models.Registration.role == "player")
            .count()
        )
        reserved = db.query(models.Reserve).filter(models.Reserve.game_id == session_id).count()
    finally:
        db.close()

    assert seated == 2, f"за столом {seated} при max_players=2"
    assert seated + reserved == len(telegram_ids), f"потеряно записей: {seated}+{reserved}"


def test_registration_cannot_be_cancelled_after_the_game_was_played(admin) -> None:
    """Отмена на проведённой игре меняла состав задним числом.

    Форма оценки подставляет участников из ростера, и уход из него после
    игры и вычёркивал сыгравшего, и молча поднимал на его место человека из
    резерва, за столом не сидевшего.
    """
    client, headers = admin
    session_id = make_session(client, headers, starts_at="2030-01-01T18:00:00Z")
    register_bot_player(client, 9101, "Сыгравший")
    register_bot_player(client, 9102, "Запасной")
    for tg in (9101, 9102):
        limiter.reset()
        client.post(
            f"/api/bot/sessions/{session_id}/register",
            headers=BOT_HEADERS,
            json={"telegram_id": tg, "role_kind": "player"},
        )
    set_game_time(session_id, starts_at="2020-01-01T18:00:00+00:00")
    limiter.reset()
    assert client.post(f"/api/admin/schedule/sessions/{session_id}/played", headers=headers).status_code == 200

    limiter.reset()
    resp = client.delete(
        f"/api/bot/sessions/{session_id}/registration",
        headers=BOT_HEADERS,
        params={"telegram_id": 9101},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert resp.json()["reason"] == "game_settled"

    db = SessionLocal()
    try:
        left = db.query(models.Registration).filter(models.Registration.game_id == session_id).count()
    finally:
        db.close()
    assert left == 2, "состав проведённой игры изменился"


def test_last_site_admin_cannot_lock_everyone_out(clean_db) -> None:
    """Удалить себя / снять с себя доступ может любой админ, кроме последнего.

    Ручки «сделать себя админом» нет намеренно, поэтому у оставшегося без
    админов сайта нет способа вернуться в /mafia/admin, кроме скрипта на
    сервере.
    """
    db = SessionLocal()
    try:
        actor = player_service.create_player(db, nickname="Организатор", slug="organizer")
        password = player_service.grant_site_access(db, player=actor, username="admin")
        db.commit()
        admin_id = actor.id
    finally:
        db.close()

    client = TestClient(app)
    limiter.reset()
    assert client.post("/api/auth/login", json={"username": "admin", "password": password}).status_code == 200
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}

    limiter.reset()
    assert client.delete(f"/api/admin/players/{admin_id}", headers=headers).status_code == 422
    limiter.reset()
    assert client.delete(f"/api/admin/players/{admin_id}/site-access", headers=headers).status_code == 422
    limiter.reset()
    assert client.get("/api/admin/players").status_code == 200, "админка потеряна"

    # Со вторым админом ограничение снимается: запирать больше нечего.
    limiter.reset()
    second = client.post(
        "/api/admin/players", json={"nickname": "Второй", "slug": "second"}, headers=headers
    ).json()
    limiter.reset()
    assert client.post(
        f"/api/admin/players/{second['id']}/site-access",
        params={"username": "second"},
        headers=headers,
    ).status_code == 200
    limiter.reset()
    assert client.delete(f"/api/admin/players/{admin_id}/site-access", headers=headers).status_code == 200
