"""Цикл «сессия создана в боте -> её проведение подтвердили -> её оценивают на
сайте» (ARCHITECTURE.md, раздел 5).

Средний шаг раньше делала фоновая задача: любая прошедшая сессия сама
становилась 'played' и попадала в «Ждут оценки» -- вместе с играми, которые не
собрались и не состоялись. Теперь этот переход делает бот-админ кнопкой, и
проверять надо ровно обратное: без подтверждения игра в очередь оценки не
попадает.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import (
    BOT_HEADERS,
    game_status,
    make_bot_admin,
    make_players,
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


def _mark_played(client, session_id: int):
    return client.post(
        f"/api/bot/admin/sessions/{session_id}/played?telegram_id={ADMIN_TG}", headers=BOT_HEADERS
    )


def _awaiting(client) -> list[int]:
    resp = client.get(
        "/api/bot/admin/sessions/awaiting-confirmation",
        headers=BOT_HEADERS,
        params={"telegram_id": ADMIN_TG},
    )
    assert resp.status_code == 200, resp.text
    return [s["id"] for s in resp.json()]


def test_past_session_waits_for_the_admin_before_it_reaches_pending_review(admin):
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client)

    # Пока игра в будущем -- ни оценивать, ни подтверждать нечего.
    assert client.get("/api/admin/games/pending-review", headers=headers).json() == []
    assert _awaiting(client) == []

    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=3))

    # Время прошло -- игра ждёт ответа админа, но в очередь оценки не идёт:
    # именно этим она и отличается от игры, которая действительно состоялась.
    assert game_status(session_id) == "scheduled"
    assert _awaiting(client) == [session_id]
    assert client.get("/api/admin/games/pending-review", headers=headers).json() == []

    assert _mark_played(client, session_id).status_code == 200

    assert game_status(session_id) == "played"
    assert _awaiting(client) == []
    pending = client.get("/api/admin/games/pending-review", headers=headers).json()
    assert [g["id"] for g in pending] == [session_id]


def test_future_game_cannot_be_marked_as_played(admin):
    client, _ = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client, days_ahead=5)

    resp = _mark_played(client, session_id)
    assert resp.status_code == 409, resp.text
    assert game_status(session_id) == "scheduled"


def test_confirming_the_same_game_twice_changes_nothing(admin):
    client, _ = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client)
    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=1))

    assert _mark_played(client, session_id).status_code == 200
    assert _mark_played(client, session_id).status_code == 409
    assert game_status(session_id) == "played"


def test_game_that_did_not_happen_is_deleted_and_leaves_no_trace(admin):
    """«Не состоялась» -- это удаление: несыгранной игре нечего делать ни в
    очереди оценки, ни в списке ожидания."""
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client)
    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=2))
    assert _awaiting(client) == [session_id]

    resp = client.delete(
        f"/api/bot/admin/sessions/{session_id}", headers=BOT_HEADERS, params={"telegram_id": ADMIN_TG}
    )
    assert resp.status_code == 200, resp.text

    assert _awaiting(client) == []
    assert client.get("/api/admin/games/pending-review", headers=headers).json() == []


def test_rated_games_leave_the_bot_schedule(admin):
    """Оценённая игра из расписания бота уходит: править состав и баллы можно
    только на сайте, а список игровых дней иначе рос бы на каждый отыгранный
    день и не сокращался никогда."""
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client)

    def bot_day_cards() -> list[str]:
        resp = client.get(
            "/api/bot/admin/sessions/day-cards", headers=headers | BOT_HEADERS,
            params={"telegram_id": ADMIN_TG},
        )
        assert resp.status_code == 200, resp.text
        return [card["day"] for card in resp.json()]

    def bot_games_on(day: str) -> list[int]:
        resp = client.get(
            "/api/bot/admin/sessions/by-day", headers=BOT_HEADERS,
            params={"telegram_id": ADMIN_TG, "day": day},
        )
        assert resp.status_code == 200, resp.text
        return [game["id"] for game in resp.json()]

    day = bot_day_cards()[0]
    assert bot_games_on(day) == [session_id]

    # Историческая игра, созданная сразу как rated, в боте тоже не появляется.
    player_ids = make_players(client, headers, 10)
    roles = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6
    rated = client.post(
        "/api/admin/games",
        json={
            "starts_at": "2026-02-01T18:00:00Z",
            "location": "Клуб",
            "game_type": "funky",
            "result": "city_win",
            "participants": [
                {"player_id": pid, "seat_number": seat, "role": role}
                for seat, (pid, role) in enumerate(zip(player_ids, roles), start=1)
            ],
        },
        headers=headers,
    )
    assert rated.status_code == 200, rated.text

    assert "01.02.2026" not in bot_day_cards()
    assert bot_games_on("01.02.2026") == []
    # Неоценённая сессия на месте: с ней боту ещё есть что делать.
    assert bot_games_on(day) == [session_id]


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
    _mark_played(client, session_id)

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
