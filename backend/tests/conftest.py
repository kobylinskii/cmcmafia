"""Общая обвязка тестов.

Переменные окружения выставляются здесь, до того как любой тест импортирует
app.config: настройки кэшируются через lru_cache, и поменять их постфактум
уже нельзя. Гоняется на реальном Postgres -- модели используют JSONB и
TIMESTAMPTZ, sqlite не подойдёт. Поднять базу:

    docker run -d --name mafia-test-db -p 55432:5432 \
        -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=mafia postgres:16
    DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55432/mafia \
        python -m alembic upgrade head
"""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("BOT_SERVICE_TOKEN", "test-bot-token")
os.environ.setdefault("REDIS_URL", "memory://")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:55432/mafia"
)
# TestClient ходит по http://testserver; Secure-кука (правильный дефолт для
# реального деплоя, см. app/config.py) была бы молча выброшена клиентом.
os.environ.setdefault("COOKIE_SECURE", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.rate_limit import limiter  # noqa: E402
from app.services import player_service  # noqa: E402

BOT_HEADERS = {"Authorization": "Bearer test-bot-token"}

_ALL_TABLES = (
    "audit_log, player_rating_history, player_rating, game_participants, "
    "reserves, registrations, games, tournament_stage_advances, tournament_stages, "
    "tournaments, pending_bot_admins, players"
)


def reset_state() -> None:
    """Возвращает процесс в исходное состояние перед тестом.

    Чистит не только базу: лимитер держит счётчики в памяти процесса и общий
    для всех тестов, так что без сброса шестой логин подряд упирается в
    5/мин и роняет тест, который про лимиты вообще не был -- причём в
    зависимости от порядка запуска файлов.
    """
    db = SessionLocal()
    try:
        db.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))
        db.commit()
    finally:
        db.close()
    limiter.reset()


@pytest.fixture
def clean_db() -> None:
    reset_state()


@pytest.fixture
def admin(clean_db) -> tuple[TestClient, dict]:
    """Залогиненный сайт-админ: (client, headers с CSRF-токеном).

    Первый админ заводится через сервисный слой, а не через API -- выдать себе
    доступ по HTTP невозможно по построению, для этого уже нужен админ.
    """
    db = SessionLocal()
    try:
        actor = player_service.create_player(db, nickname="Организатор", slug="organizer")
        password = player_service.grant_site_access(db, player=actor, username="admin")
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200, resp.text
    return client, {"X-CSRF-Token": client.cookies.get("csrf_token")}


def make_players(client: TestClient, headers: dict, count: int) -> list[int]:
    """Заводит count игроков через админку, возвращает их id."""
    ids = []
    for i in range(1, count + 1):
        resp = client.post(
            "/api/admin/players",
            json={"nickname": f"Игрок{i}", "slug": f"player{i}"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        ids.append(resp.json()["id"])
    return ids


def register_bot_player(client: TestClient, telegram_id: int, nickname: str) -> dict:
    """Регистрирует пользователя бота через тот же эндпоинт, что и живой бот."""
    resp = client.post(
        "/api/bot/players/register",
        headers=BOT_HEADERS,
        json={
            "telegram_id": telegram_id,
            "phone": f"7900{telegram_id:07d}",
            "nickname": nickname,
            "salutation": "т",
            "affiliation": "vmk",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def admin_with_password(clean_db) -> tuple[TestClient, dict, str]:
    """То же, что admin, но отдаёт ещё и пароль -- нужен тестам, которые его
    меняют. Отдельной фикстурой, чтобы не ломать распаковку в существующих."""
    db = SessionLocal()
    try:
        actor = player_service.create_player(db, nickname="Организатор", slug="organizer")
        password = player_service.grant_site_access(db, player=actor, username="admin")
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200, resp.text
    return client, {"X-CSRF-Token": client.cookies.get("csrf_token")}, password


def make_tournament(client: TestClient, headers: dict, *, name: str = "Кубок ВМК",
                    slug: str = "kubok-vmk", location: str | None = "ВМК МГУ",
                    starts_at: str = "2025-01-10T00:00:00+00:00",
                    ends_at: str = "2025-01-11T00:00:00+00:00") -> int:
    """Турнирная игра обязана принадлежать турниру, поэтому почти всякий тест,
    создающий рейтинговую игру, сначала заводит турнир."""
    resp = client.post(
        "/api/admin/tournaments",
        json={"name": name, "slug": slug, "location": location, "starts_at": starts_at, "ends_at": ends_at},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def make_tournament_game(
    client: TestClient, headers: dict, *, tournament_id: int, participants: list[dict],
    stage_id: int | None = None, starts_at: str = "2026-01-01T18:00:00Z",
    location: str = "Клуб", result: str = "mafia_win", notes: str | None = None,
) -> dict:
    """Турнирная игра больше не создаётся одним POST: сперва заводится пустой
    слот (общий на турнир -- для простого турнира без сетки, или внутри
    конкретного этапа -- для турнира с квалификацией), потом слот оценивается
    отдельным PUT (см. app.routers.admin, раздел «Турниры»)."""
    add_url = (
        f"/api/admin/tournaments/{tournament_id}/stages/{stage_id}/games"
        if stage_id is not None
        else f"/api/admin/tournaments/{tournament_id}/games"
    )
    add_resp = client.post(add_url, json={"count": 1}, headers=headers)
    assert add_resp.status_code == 200, add_resp.text
    game_id = add_resp.json()[0]["id"]

    body = {"starts_at": starts_at, "location": location, "result": result, "participants": participants}
    if notes is not None:
        body["notes"] = notes
    put_resp = client.put(f"/api/admin/games/{game_id}", json=body, headers=headers)
    assert put_resp.status_code == 200, put_resp.text
    return put_resp.json()


def make_bot_admin(telegram_id: int, *, nickname: str, slug: str) -> int:
    """Заводит игрока с telegram_id и сразу выдаёт ему права бот-админа
    (через сервисный слой: выдать их себе по API нельзя, нужен уже админ)."""
    db = SessionLocal()
    try:
        player = player_service.create_player(
            db, nickname=nickname, slug=slug, telegram_id=telegram_id
        )
        player.is_bot_admin = True
        db.commit()
        return player.id
    finally:
        db.close()


_UNSET = object()


def set_game_time(game_id: int, *, starts_at=_UNSET, registration_until=_UNSET) -> None:
    """Двигает время игры напрямую в БД. Сессию в прошлом через API не создать
    (да и незачем), а перевод в 'played' проверяется именно на прошедших."""
    db = SessionLocal()
    try:
        game = db.get(models.Game, game_id)
        if starts_at is not _UNSET:
            game.starts_at = starts_at
        if registration_until is not _UNSET:
            game.registration_until = registration_until
        db.commit()
    finally:
        db.close()


def game_status(game_id: int) -> str:
    db = SessionLocal()
    try:
        return db.get(models.Game, game_id).status
    finally:
        db.close()
