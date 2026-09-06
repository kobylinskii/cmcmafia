"""Модерация игроков, пришедших из бота.

Регистрация в боте открыта кому угодно, поэтому новый человек не должен
попадать на публичную часть сайта до решения админа -- но и ждать это решение,
чтобы записаться на игру, он не должен. Оба свойства проверяются здесь, как и
доставка решения обратно в бот.
"""

from __future__ import annotations

from tests.conftest import (
    BOT_HEADERS,
    make_players,
    make_tournament,
    make_tournament_game,
    register_bot_player,
)

ROLES = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6


def _pending(client, headers) -> list[dict]:
    resp = client.get("/api/admin/players/pending", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _profile(client, telegram_id: int) -> dict:
    resp = client.get(
        "/api/bot/players/me", headers=BOT_HEADERS, params={"telegram_id": telegram_id}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_bot_registration_starts_pending_and_is_hidden_from_the_site(admin):
    client, headers = admin
    player = register_bot_player(client, 5001, "Новичок")

    assert player["confirmation_status"] == "pending"
    assert [p["nickname"] for p in _pending(client, headers)] == ["Новичок"]

    slugs = [p["slug"] for p in client.get("/api/players").json()]
    assert player["slug"] not in slugs
    assert client.get(f"/api/players/{player['slug']}").status_code == 404


def test_player_created_by_admin_is_confirmed_immediately(admin):
    """Игрока на сайте заводит тот, кто его уже проверил -- второй раз
    подтверждать некого."""
    client, headers = admin
    make_players(client, headers, 1)

    assert _pending(client, headers) == []
    assert client.get("/api/players/player1").status_code == 200


def test_confirm_puts_the_player_on_the_site(admin):
    client, headers = admin
    player = register_bot_player(client, 5002, "Новичок")
    player_id = _pending(client, headers)[0]["id"]

    resp = client.post(f"/api/admin/players/{player_id}/confirm", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["confirmation_status"] == "confirmed"

    assert _pending(client, headers) == []
    assert client.get(f"/api/players/{player['slug']}").status_code == 200
    assert _profile(client, 5002)["confirmation_status"] == "confirmed"


def test_unconfirmed_player_is_absent_from_the_rating_until_confirmed(admin):
    """Рейтинг -- главное место, где неподтверждённого быть не должно: игру он
    сыграть успел, а проверку ещё не прошёл."""
    client, headers = admin
    ids = make_players(client, headers, 9)
    newcomer = register_bot_player(client, 5003, "Новичок")
    pending_id = _pending(client, headers)[0]["id"]
    tid = make_tournament(client, headers)
    make_tournament_game(
        client, headers, tournament_id=tid, starts_at="2026-02-01T18:00:00Z",
        participants=[
            {"player_id": pid, "seat_number": seat, "role": role}
            for seat, (pid, role) in enumerate(zip([*ids, pending_id], ROLES), start=1)
        ],
    )

    nicknames = [row["nickname"] for row in client.get("/api/rating").json()["items"]]
    assert newcomer["nickname"] not in nicknames
    assert len(nicknames) == 9

    client.post(f"/api/admin/players/{pending_id}/confirm", headers=headers)
    nicknames = [row["nickname"] for row in client.get("/api/rating").json()["items"]]
    assert newcomer["nickname"] in nicknames
    assert len(nicknames) == 10


def test_invited_bot_admin_is_confirmed_on_arrival(admin):
    """Приглашённого админа подтверждать некому: права ему выдал действующий
    админ, а до /start он ещё и не мог подать заявку."""
    client, headers = admin
    invite = client.post("/api/admin/bot-admins", params={"username": "@newadmin"}, headers=headers)
    assert invite.status_code == 200, invite.text

    resp = client.post(
        "/api/bot/players/register",
        headers=BOT_HEADERS,
        json={
            "telegram_id": 5020,
            "telegram_username": "newadmin",
            "phone": "79000005020",
            "nickname": "Организатор2",
            "salutation": "т",
            "affiliation": "vmk",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_bot_admin"] is True
    assert resp.json()["confirmation_status"] == "confirmed"
    assert _pending(client, headers) == []


def test_reject_requires_a_reason_and_reaches_the_player(admin):
    client, headers = admin
    register_bot_player(client, 5004, "Новичок")
    player_id = _pending(client, headers)[0]["id"]

    empty = client.post(
        f"/api/admin/players/{player_id}/reject", json={"reason": "   "}, headers=headers
    )
    assert empty.status_code == 422

    resp = client.post(
        f"/api/admin/players/{player_id}/reject",
        json={"reason": "ФИО не совпадает с профилем"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    profile = _profile(client, 5004)
    assert profile["confirmation_status"] == "rejected"
    assert profile["rejection_reason"] == "ФИО не совпадает с профилем"
    assert _pending(client, headers) == []


def test_rejected_player_can_ask_for_a_second_look(admin):
    client, headers = admin
    register_bot_player(client, 5005, "Новичок")
    player_id = _pending(client, headers)[0]["id"]
    client.post(
        f"/api/admin/players/{player_id}/reject", json={"reason": "Проверьте ФИО"}, headers=headers
    )

    resp = client.post(
        "/api/bot/players/me/resubmit", headers=BOT_HEADERS, params={"telegram_id": 5005}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["confirmation_status"] == "pending"
    assert resp.json()["rejection_reason"] is None
    assert len(_pending(client, headers)) == 1

    # Подтверждённому повторная проверка не нужна -- и не должна ронять статус.
    again = client.post(
        "/api/bot/players/me/resubmit", headers=BOT_HEADERS, params={"telegram_id": 5005}
    )
    assert again.status_code == 409


def test_decisions_queue_up_for_the_bot_and_clear_on_ack(admin):
    """Бэкенд в Telegram не пишет: он копит решения, бот их забирает и
    подтверждает доставку. Без ack'а очередь не должна пустеть."""
    client, headers = admin
    register_bot_player(client, 5006, "Новичок")
    player_id = _pending(client, headers)[0]["id"]
    client.post(f"/api/admin/players/{player_id}/confirm", headers=headers)

    queue = client.get("/api/bot/players/confirmation-notifications", headers=BOT_HEADERS).json()
    assert [(item["telegram_id"], item["confirmation_status"]) for item in queue] == [
        (5006, "confirmed")
    ]

    # Повторный опрос до ack'а всё ещё отдаёт заявку: сообщение могло не уйти.
    assert len(client.get("/api/bot/players/confirmation-notifications", headers=BOT_HEADERS).json()) == 1

    ack = client.post(
        "/api/bot/players/confirmation-notifications/ack",
        headers=BOT_HEADERS,
        json={"player_ids": [player_id]},
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["marked"] == 1
    assert client.get("/api/bot/players/confirmation-notifications", headers=BOT_HEADERS).json() == []


def test_duplicate_phone_is_refused_politely(admin):
    """players.phone UNIQUE: раньше второй такой же номер долетал до
    констрейнта и возвращался пятисоткой."""
    client, _ = admin
    register_bot_player(client, 5007, "Первый")

    resp = client.post(
        "/api/bot/players/register",
        headers=BOT_HEADERS,
        json={
            "telegram_id": 5008,
            "phone": "79000005007",
            "nickname": "Второй",
            "salutation": "т",
            "affiliation": "vmk",
        },
    )
    assert resp.status_code == 409, resp.text
    assert "телефон" in resp.json()["detail"].lower()
