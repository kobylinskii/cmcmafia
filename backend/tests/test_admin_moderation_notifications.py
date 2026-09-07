"""Оповещение админов сайта о новых заявках и правках профиля.

Зеркало очередей из test_player_confirmation / test_profile_change_moderation:
там сайт копит решения, а бот разносит их игрокам; здесь бот копит новые
pending-строки и разносит их админам сайта. Бэкенд в Telegram не пишет --
проверяем ровно то, что бот забирает опросом и подтверждает ack'ом.
"""

from __future__ import annotations

from app import models
from app.database import SessionLocal
from tests.conftest import BOT_HEADERS, register_bot_player

ADMIN_TG = 700001


def _link_admin_telegram(telegram_id: int = ADMIN_TG) -> None:
    """Привязывает Telegram к сайт-админу из фикстуры: без telegram_id админ в
    рассылку не попадает (писать некуда)."""
    db = SessionLocal()
    try:
        admin = db.query(models.Player).filter(models.Player.is_site_admin.is_(True)).one()
        admin.telegram_id = telegram_id
        db.commit()
    finally:
        db.close()


def _queue(client) -> dict:
    resp = client.get("/api/bot/admin-notifications", headers=BOT_HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _pending_id(client, headers) -> int:
    return client.get("/api/admin/players/pending", headers=headers).json()[0]["id"]


def _confirm_player(client, headers, telegram_id: int, nickname: str) -> int:
    register_bot_player(client, telegram_id, nickname)
    player_id = _pending_id(client, headers)
    resp = client.post(f"/api/admin/players/{player_id}/confirm", headers=headers)
    assert resp.status_code == 200, resp.text
    return player_id


def test_new_registration_reaches_the_admin_queue_with_recipients(admin):
    client, headers = admin
    _link_admin_telegram()
    register_bot_player(client, 5101, "Новичок")

    queue = _queue(client)
    assert queue["recipients"] == [ADMIN_TG]
    assert [r["nickname"] for r in queue["registrations"]] == ["Новичок"]
    assert queue["registrations"][0]["affiliation"] == "vmk"
    assert queue["profile_changes"] == []


def test_registration_clears_from_the_queue_only_on_ack(admin):
    client, headers = admin
    _link_admin_telegram()
    register_bot_player(client, 5102, "Новичок")
    player_id = _pending_id(client, headers)

    # Повторный опрос до ack'а всё ещё отдаёт заявку: сообщение могло не уйти.
    assert len(_queue(client)["registrations"]) == 1
    assert len(_queue(client)["registrations"]) == 1

    ack = client.post(
        "/api/bot/admin-notifications/ack",
        headers=BOT_HEADERS,
        json={"registration_player_ids": [player_id]},
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["marked_registrations"] == 1
    assert _queue(client)["registrations"] == []


def test_profile_change_reaches_the_queue_and_clears_on_ack(admin):
    client, headers = admin
    _link_admin_telegram()
    _confirm_player(client, headers, 5103, "Шериф")

    resp = client.put(
        "/api/bot/players/me?telegram_id=5103",
        headers=BOT_HEADERS,
        json={"full_name": "Петров Пётр Петрович"},
    )
    assert resp.status_code == 200, resp.text

    queue = _queue(client)
    assert queue["registrations"] == []
    assert len(queue["profile_changes"]) == 1
    change = queue["profile_changes"][0]
    assert change["player_nickname"] == "Шериф"
    assert change["field_label"] == "ФИО"
    assert change["current_value"] is None
    assert change["new_value"] == "Петров Пётр Петрович"

    ack = client.post(
        "/api/bot/admin-notifications/ack",
        headers=BOT_HEADERS,
        json={"profile_change_ids": [change["change_id"]]},
    )
    assert ack.json()["marked_profile_changes"] == 1
    assert _queue(client)["profile_changes"] == []


def test_admin_decision_removes_the_registration_from_the_queue_even_without_ack(admin):
    """Заявку, которую админ уже разобрал, боту оповещать не о чем -- она
    выходит из очереди по смене статуса, а не по ack'у."""
    client, headers = admin
    _link_admin_telegram()
    register_bot_player(client, 5104, "Новичок")
    player_id = _pending_id(client, headers)

    client.post(
        f"/api/admin/players/{player_id}/reject",
        headers=headers,
        json={"reason": "ФИО не совпадает"},
    )
    assert _queue(client)["registrations"] == []


def test_resubmit_puts_the_registration_back_in_the_admin_queue(admin):
    client, headers = admin
    _link_admin_telegram()
    register_bot_player(client, 5105, "Новичок")
    player_id = _pending_id(client, headers)
    client.post(
        "/api/bot/admin-notifications/ack",
        headers=BOT_HEADERS,
        json={"registration_player_ids": [player_id]},
    )
    assert _queue(client)["registrations"] == []

    client.post(
        f"/api/admin/players/{player_id}/reject", headers=headers, json={"reason": "Проверьте ФИО"}
    )
    resp = client.post(
        "/api/bot/players/me/resubmit", headers=BOT_HEADERS, params={"telegram_id": 5105}
    )
    assert resp.status_code == 200, resp.text

    # Повторная подача -- новое событие: заявка снова в очереди оповещения.
    assert [r["player_id"] for r in _queue(client)["registrations"]] == [player_id]


def test_no_recipients_when_no_site_admin_has_telegram(admin):
    """Админ сайта без привязанного Telegram в рассылку не попадает: очередь
    видна, но получателей нет, и бот её не трогает."""
    client, headers = admin
    register_bot_player(client, 5106, "Новичок")

    queue = _queue(client)
    assert queue["recipients"] == []
    assert len(queue["registrations"]) == 1
