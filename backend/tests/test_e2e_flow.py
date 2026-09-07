"""Сквозной интеграционный прогон: сайт-админка создаёт игроков и рейтинговую
игру -> публичное API отдаёт рейтинг/статистику -> бот регистрирует игрока,
создаёт сессию, записывает/резервирует/отменяет с авто-промоушеном.

Гоняется на реальном Postgres (см. DATABASE_URL) — модели используют
Postgres-специфичные типы (JSONB, TIMESTAMPTZ), sqlite не подходит.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.services import player_service
from app.timeutil import club_day

# Настройка окружения и очистка базы -- в tests/conftest.py: pytest импортирует
# его раньше любого тестового модуля, то есть до того, как app.config закэширует
# настройки через lru_cache.
from tests.conftest import (
    BOT_HEADERS,
    make_session,
    make_sessions,
    make_tournament,
    make_tournament_game,
    reset_state,
    set_game_max_players,
)


def test_full_flow():
    reset_state()
    client = TestClient(app)

    # --- bootstrap a site admin directly through the service layer ---
    db = SessionLocal()
    admin = player_service.create_player(db, nickname="Организатор", slug="organizer")
    temp_password = player_service.grant_site_access(db, player=admin, username="admin")
    admin.is_site_admin = True
    db.commit()
    db.close()

    # --- login ---
    resp = client.post("/api/auth/login", json={"username": "admin", "password": temp_password})
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_site_admin"] is True
    csrf = client.cookies.get("csrf_token")
    assert csrf

    def admin_headers() -> dict:
        return {"X-CSRF-Token": csrf}

    # --- wrong password should fail cleanly ---
    bad = TestClient(app)
    resp = bad.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401

    # --- create 10 players for a full table ---
    player_slugs = []
    for i in range(1, 11):
        resp = client.post(
            "/api/admin/players",
            json={"nickname": f"Игрок{i}", "slug": f"player{i}"},
            headers=admin_headers(),
        )
        assert resp.status_code == 200, resp.text
        player_slugs.append(resp.json()["slug"])

    # fetch numeric ids
    resp = client.get("/api/players")
    assert resp.status_code == 200
    by_slug = {p["slug"]: p for p in resp.json()}
    assert len(by_slug) == 11  # +organizer

    db = SessionLocal()
    from app import models

    id_by_slug = {
        row.slug: row.id
        for row in db.query(models.Player).filter(models.Player.slug.in_(player_slugs)).all()
    }
    db.close()

    # roles: 2 mafia, 1 don, 6 citizen, 1 sheriff -> classic 10-player table.
    # Winners get points_win + a judge bonus so Sa (4.0) clears the E*M=3.5
    # break-even threshold -- otherwise even the winning team loses rating,
    # which is correct per the formula (see ARCHITECTURE.md) but would make
    # a naive "winners always gain rating" assertion below wrong, not the code.
    roles = ["don", "mafia", "mafia"] + ["sheriff"] + ["citizen"] * 6
    participants = []
    for seat, (slug, role) in enumerate(zip(player_slugs, roles), start=1):
        p = {"player_id": id_by_slug[slug], "seat_number": seat, "role": role}
        if role in ("mafia", "don"):
            p["points_win"] = 2.5
            p["points_judge"] = 1.5
        participants.append(p)

    tournament_id = make_tournament(client, admin_headers())

    # Турнирная игра теперь создаётся не одним POST: сперва слот (см.
    # «Турниры» в админке), потом его оценка -- см. make_tournament_game.
    game = make_tournament_game(
        client, admin_headers(), tournament_id=tournament_id,
        starts_at="2026-01-10T18:00:00Z", participants=participants,
    )
    assert game["status"] == "rated"
    assert len(game["participants"]) == 10

    # --- public: games list + detail ---
    resp = client.get("/api/games")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    resp = client.get(f"/api/games/{game['id']}")
    assert resp.status_code == 200

    # --- public: rating table reflects Elo movement away from the 1000 start ---
    resp = client.get("/api/rating")
    assert resp.status_code == 200
    rating_rows = {row["slug"]: row for row in resp.json()["items"]}
    assert len(rating_rows) == 10
    winner = rating_rows["player1"]  # don, on the winning black team
    loser = rating_rows["player4"]  # sheriff, on the losing red team

    # K=40 (games_before<30), E=0.5 (equal 1000-rating teams before this game),
    # M=7: winner Sa=2.5+1.5=4.0 -> 1000 + 40*(4.0-3.5)/7 ~= 1002.86
    # loser  Sa=0             -> 1000 + 40*(0.0-3.5)/7   ~= 980.00
    assert winner["rating"] == pytest.approx(1002.86, abs=0.01)
    assert loser["rating"] == pytest.approx(980.0, abs=0.01)
    assert winner["games_count"] == 1

    # --- public: player stats page ---
    resp = client.get("/api/players/player1")
    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["total_games"] == 1
    assert stats["wins"] == 1
    assert stats["don_games"] == 1
    assert stats["don_win_rate"] == 1.0

    # --- admin: bad game (9 participants) is rejected and does not corrupt state ---
    resp = client.post(
        "/api/admin/games",
        json={
            "starts_at": "2026-01-11T18:00:00Z",
            "result": "city_win",
            "participants": participants[:9],
        },
        headers=admin_headers(),
    )
    assert resp.status_code == 422

    # --- CSRF: mutating request without token must be rejected ---
    resp = client.delete(f"/api/admin/games/{game['id']}")
    assert resp.status_code == 403

    # ============= BOT FLOW =============

    # register a new bot user
    resp = client.post(
        "/api/bot/players/register",
        headers=BOT_HEADERS,
        json={
            "telegram_id": 111,
            "telegram_username": "newbie",
            "phone": "+7 900 123-45-67",
            "nickname": "Новичок",
            "salutation": "товарищ",
            "affiliation": "vmk",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["slug"]  # auto-suggested

    # duplicate telegram_id is rejected
    resp = client.post(
        "/api/bot/players/register",
        headers=BOT_HEADERS,
        json={
            "telegram_id": 111,
            "phone": "+7 900 000-00-02",
            "nickname": "Дубль",
            "salutation": "т",
            "affiliation": "vmk",
        },
    )
    assert resp.status_code == 409

    # сессию для записи планирует сайт-админ: планировщик переехал из бота в
    # админку сайта, бот-ручки создания слотов больше нет
    session_id = make_session(client, admin_headers(), starts_at="2026-12-01T18:00:00Z", location="Клуб")
    set_game_max_players(session_id, 2)

    # без сессии сайт-админа планировщик недоступен (кука есть только у client)
    resp = TestClient(app).post(
        "/api/admin/schedule/plan",
        json={"starts_at": "2026-12-01T18:00:00Z", "count": 1, "location": "x", "game_type": "funky"},
    )
    assert resp.status_code == 401

    # register two more bot users to fill the 2-player session + one reserve
    for i, tg_id in enumerate([201, 202, 203], start=1):
        resp = client.post(
            "/api/bot/players/register",
            headers=BOT_HEADERS,
            json={
                "telegram_id": tg_id,
                "phone": f"7900000000{i}",
                "nickname": f"Бот{i}",
                "salutation": "т",
                "affiliation": "vmk",
            },
        )
        assert resp.status_code == 200, resp.text

    for tg_id in (201, 202):
        resp = client.post(
            f"/api/bot/sessions/{session_id}/register",
            headers=BOT_HEADERS,
            json={"telegram_id": tg_id, "role_kind": "player"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    # third player: main roster full (max_players=2) -> the same call puts them
    # in the reserve queue, no second step
    resp = client.post(
        f"/api/bot/sessions/{session_id}/register",
        headers=BOT_HEADERS,
        json={"telegram_id": 203, "role_kind": "player"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["is_reserve"] is True
    assert body["reserve_position"] == 1

    # player 201 cancels -> 203 should be auto-promoted from reserve
    resp = client.delete(
        f"/api/bot/sessions/{session_id}/registration?telegram_id=201",
        headers=BOT_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["promoted_telegram_id"] == 203

    # 203's own registrations should now show the game as a 'player', not reserve
    resp = client.get("/api/bot/registrations/mine", headers=BOT_HEADERS, params={"telegram_id": 203})
    assert resp.status_code == 200
    regs = resp.json()
    assert len(regs) == 1
    assert regs[0]["role"] == "player"
    assert regs[0]["is_reserve"] is False

    # roster is visible to any registered bot user, not just admins
    resp = client.get(f"/api/bot/sessions/{session_id}/roster", headers=BOT_HEADERS, params={"telegram_id": 202})
    assert resp.status_code == 200
    roster = resp.json()
    assert {m["telegram_id"] for m in roster["registrations"]} == {202, 203}

    print("E2E flow OK")


def _site_admin_client() -> tuple[TestClient, dict]:
    db = SessionLocal()
    actor = player_service.create_player(db, nickname="Организатор", slug="organizer")
    password = player_service.grant_site_access(db, player=actor, username="admin")
    db.commit()
    db.close()
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": password})
    assert resp.status_code == 200, resp.text
    return client, {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_schedule_planner_flow():
    """Планировщик игр в админке сайта: пачка слотов, обзор по дням, конфликты.

    До переноса тем же занималась админка бота (`/api/bot/admin/sessions/*`);
    ручек больше нет, расписание ведёт сайт-админ.
    """
    reset_state()
    client, headers = _site_admin_client()

    # Дата считается от «сегодня», а не зашита строкой: у прошедшего дня
    # awaiting_count не ноль, и такой тест начинал бы врать со временем.
    first = (datetime.now(timezone.utc) + timedelta(days=30)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    day = club_day(first)

    # день из трёх слотов по часу
    created = make_sessions(
        client, headers, starts_at=first.isoformat(), location="Клуб", count=3, step_minutes=60
    )
    assert [datetime.fromisoformat(s["starts_at"]) for s in created] == [
        first,
        first + timedelta(hours=1),
        first + timedelta(hours=2),
    ]
    assert all(s["needs_rating"] for s in created)

    # обзор по дням: одна строка со счётчиками
    resp = client.get("/api/admin/schedule/days", headers=headers)
    assert resp.status_code == 200, resp.text
    assert [(d["day"], d["types"], d["games_count"], d["awaiting_count"]) for d in resp.json()] == [
        (day, ["funky"], 3, 0)
    ]

    # игры дня -- все три
    resp = client.get("/api/admin/schedule/sessions", headers=headers, params={"day": day})
    assert resp.status_code == 200
    assert len(resp.json()) == 3

    # предпросмотр плана показывает конфликты до записи: первое время занято,
    # третьим часом позже -- свободно
    resp = client.post(
        "/api/admin/schedule/plan/preview",
        headers=headers,
        json={
            "starts_at": first.isoformat(),
            "count": 2,
            "step_minutes": 180,
            "location": "Клуб",
            "game_type": "funky",
        },
    )
    assert resp.status_code == 200, resp.text
    assert [datetime.fromisoformat(v) for v in resp.json()["starts_at_list"]] == [
        first,
        first + timedelta(hours=3),
    ]
    assert [datetime.fromisoformat(v) for v in resp.json()["conflicts"]] == [first]

    # шаг может быть любым в разумных пределах, но не меньше получаса
    bad = client.post(
        "/api/admin/schedule/plan",
        headers=headers,
        json={
            "starts_at": (first + timedelta(days=1)).isoformat(),
            "count": 2,
            "step_minutes": 5,
            "location": "Клуб",
            "game_type": "funky",
        },
    )
    assert bad.status_code == 422

    # правка слота: место и формат
    session_id = created[0]["id"]
    resp = client.put(
        f"/api/admin/schedule/sessions/{session_id}",
        headers=headers,
        json={"location": "ВМК МГУ, ауд. 685", "game_type": "training"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["location"] == "ВМК МГУ, ауд. 685"
    assert resp.json()["game_type"] == "training"

    # места прошлых игр предлагаются в форме, чтобы их не набирали руками
    resp = client.get("/api/admin/schedule/locations", headers=headers)
    assert resp.status_code == 200
    assert "ВМК МГУ, ауд. 685" in resp.json()

    # удаление слота убирает его из дня
    assert client.delete(f"/api/admin/schedule/sessions/{session_id}", headers=headers).status_code == 200
    resp = client.get("/api/admin/schedule/sessions", headers=headers, params={"day": day})
    # Остались вторая и третья игры дня -- но уже под номерами 1 и 2: удаление
    # не оставляет дыру в нумерации, а сдвигает всё, что стояло после
    # (game_service.resequence_game_ids).
    assert [s["starts_at"] for s in resp.json()] == [g["starts_at"] for g in created[1:]]
    assert [s["id"] for s in resp.json()] == [1, 2]

    print("Schedule planner flow OK")


def test_bot_admin_management_flow():
    """В боте от админки остались только права: выдать, увидеть, снять.

    Назначение по @username человека, который ещё не открывал бота, -- ровно то,
    чего на сайте не сделать: telegram_id у него появится только при /start.
    """
    reset_state()
    client = TestClient(app)

    resp = client.post(
        "/api/bot/players/register",
        headers=BOT_HEADERS,
        json={
            "telegram_id": 501,
            "telegram_username": "sched_admin",
            "phone": "+7 900 111-11-11",
            "nickname": "Расписатель",
            "salutation": "т",
            "affiliation": "vmk",
        },
    )
    assert resp.status_code == 200

    db = SessionLocal()
    from app import models

    admin = db.query(models.Player).filter(models.Player.telegram_id == 501).one()
    admin.is_bot_admin = True
    db.commit()
    db.close()

    # поиск человека по @username / телефону -- шаг назначения админа
    resp = client.get(
        "/api/bot/admin/players/by-username", headers=BOT_HEADERS, params={"telegram_id": 501, "username": "sched_admin"}
    )
    assert resp.status_code == 200
    assert resp.json()["telegram_id"] == 501

    resp = client.get(
        "/api/bot/admin/players/by-phone", headers=BOT_HEADERS, params={"telegram_id": 501, "phone": "+7 900 111-11-11"}
    )
    assert resp.status_code == 200
    assert resp.json()["nickname"] == "Расписатель"

    # grant a pending admin by username (user not registered yet) -> then registering consumes it
    resp = client.post(
        "/api/bot/admin/admins?telegram_id=501",
        headers=BOT_HEADERS,
        json={"username": "future_admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    resp = client.get("/api/bot/admin/admins/pending?telegram_id=501", headers=BOT_HEADERS)
    assert resp.json() == ["future_admin"]

    resp = client.post(
        "/api/bot/players/register",
        headers=BOT_HEADERS,
        json={
            "telegram_id": 502,
            "telegram_username": "future_admin",
            "phone": "+7 900 222-22-22",
            "nickname": "БудущийАдмин",
            "salutation": "т",
            "affiliation": "vmk",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["is_bot_admin"] is True  # granted automatically on registration

    resp = client.get("/api/bot/admin/admins/pending?telegram_id=501", headers=BOT_HEADERS)
    assert resp.json() == []  # consumed

    resp = client.get("/api/bot/admin/admins?telegram_id=501", headers=BOT_HEADERS)
    admins = {a["telegram_id"] for a in resp.json()}
    assert admins == {501, 502}

    # remove an admin by telegram_id
    resp = client.delete("/api/bot/admin/admins/by-telegram/502?telegram_id=501", headers=BOT_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["removed"] is True

    # расписанием бот-админ больше не управляет: ручки просто нет
    gone = client.post(
        "/api/bot/admin/sessions?telegram_id=501",
        headers=BOT_HEADERS,
        json={"starts_at": "2026-03-05T18:00:00Z", "location": "Клуб", "game_type": "funky"},
    )
    assert gone.status_code == 404

    print("Bot admin management flow OK")


def test_bootstrap_admin_via_config(monkeypatch):
    """A telegram_id listed in SUPERADMIN_TELEGRAM_IDS gets is_bot_admin=True purely
    from config, both at registration and on every subsequent /players/me sync --
    this replaces the bot's old direct-DB ensure_superadmin/ensure_admin_by_phone,
    which would otherwise be an unauthenticated privilege escalation over the API
    (granting admin normally requires already being one)."""
    reset_state()
    client = TestClient(app)

    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SUPERADMIN_TELEGRAM_IDS_RAW", "999")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PHONE_RAW", "79001234567")
    get_settings.cache_clear()
    try:
        # superadmin by telegram_id -> granted at registration time
        resp = client.post(
            "/api/bot/players/register",
            headers=BOT_HEADERS,
            json={
                "telegram_id": 999,
                "phone": "+7 111 111-11-11",
                "nickname": "Супер",
                "salutation": "т",
                "affiliation": "vmk",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["is_bot_admin"] is True

        # bootstrap by phone -> not admin at registration (config only matches phone,
        # verify a random phone does NOT get granted)
        resp = client.post(
            "/api/bot/players/register",
            headers=BOT_HEADERS,
            json={
                "telegram_id": 998,
                "phone": "+7 222 222-22-22",
                "nickname": "Обычный",
                "salutation": "т",
                "affiliation": "vmk",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["is_bot_admin"] is False

        # a plain user cannot self-grant admin over the API
        resp = client.post(
            "/api/bot/admin/admins?telegram_id=998",
            headers=BOT_HEADERS,
            json={"telegram_id": 998},
        )
        assert resp.status_code == 403
    finally:
        get_settings.cache_clear()

    print("Bootstrap admin config flow OK")
