"""Модерация заявок и правок профиля прямо из Telegram.

Те же операции, что и на вкладке «Обзор» в админке сайта, только вызванные
кнопкой под сообщением бота: админ клуба живёт в боте, и лишний вход в
браузер откладывал проверку на сутки.

Проверяется главное: решение принимает только админ, решённое второй раз не
принимается, а игрок узнаёт о решении через ту же очередь доставки, что и
раньше (бэкенд в Telegram не ходит).
"""

from __future__ import annotations

from app import models
from app.database import SessionLocal
from tests.conftest import BOT_HEADERS, register_bot_player

ADMIN_TG = 710001
PLAYER_TG = 710002


def _make_bot_admin(telegram_id: int) -> int:
    db = SessionLocal()
    try:
        player = db.query(models.Player).filter(models.Player.telegram_id == telegram_id).one()
        player.is_bot_admin = True
        db.commit()
        return player.id
    finally:
        db.close()


def _admin(client) -> int:
    register_bot_player(client, ADMIN_TG, "Распорядитель")
    return _make_bot_admin(ADMIN_TG)


def _player_id(telegram_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(models.Player).filter(models.Player.telegram_id == telegram_id).one().id
    finally:
        db.close()


def _profile(client, telegram_id: int) -> dict:
    resp = client.get(
        "/api/bot/players/me", headers=BOT_HEADERS, params={"telegram_id": telegram_id}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_admin_confirms_a_registration_from_the_bot(admin):
    client, _ = admin
    _admin(client)
    register_bot_player(client, PLAYER_TG, "Новичок")
    player_id = _player_id(PLAYER_TG)

    resp = client.post(
        f"/api/bot/moderation/registrations/{player_id}/confirm?telegram_id={ADMIN_TG}",
        headers=BOT_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert _profile(client, PLAYER_TG)["confirmation_status"] == "confirmed"

    # Второе нажатие той же кнопки (сообщение остаётся в чате навсегда) -- отказ,
    # а не молчаливое повторное подтверждение.
    again = client.post(
        f"/api/bot/moderation/registrations/{player_id}/confirm?telegram_id={ADMIN_TG}",
        headers=BOT_HEADERS,
    )
    assert again.status_code == 409


def test_admin_rejects_a_registration_with_a_reason(admin):
    client, _ = admin
    _admin(client)
    register_bot_player(client, PLAYER_TG, "Новичок")
    player_id = _player_id(PLAYER_TG)

    resp = client.post(
        f"/api/bot/moderation/registrations/{player_id}/reject?telegram_id={ADMIN_TG}",
        headers=BOT_HEADERS,
        json={"reason": "ФИО не совпадает с документом"},
    )
    assert resp.status_code == 200, resp.text

    profile = _profile(client, PLAYER_TG)
    assert profile["confirmation_status"] == "rejected"
    assert profile["rejection_reason"] == "ФИО не совпадает с документом"

    # Решение уезжает игроку той же очередью, что и решение с сайта.
    queue = client.get("/api/bot/players/confirmation-notifications", headers=BOT_HEADERS).json()
    assert [item["telegram_id"] for item in queue] == [PLAYER_TG]


def test_admin_applies_and_rejects_profile_changes_from_the_bot(admin):
    client, headers = admin
    _admin(client)
    register_bot_player(client, PLAYER_TG, "Новичок")
    player_id = _player_id(PLAYER_TG)
    client.post(f"/api/admin/players/{player_id}/confirm", headers=headers)

    client.put(
        f"/api/bot/players/me?telegram_id={PLAYER_TG}",
        headers=BOT_HEADERS,
        json={"bio": "Играю с 2015 года", "age": 30},
    )
    queue = client.get("/api/admin/players/profile-changes", headers=headers).json()
    by_field = {row["field"]: row["id"] for row in queue}
    assert set(by_field) == {"bio", "age"}

    applied = client.post(
        f"/api/bot/moderation/profile-changes/{by_field['bio']}/apply?telegram_id={ADMIN_TG}",
        headers=BOT_HEADERS,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["new_value"] == "Играю с 2015 года"

    rejected = client.post(
        f"/api/bot/moderation/profile-changes/{by_field['age']}/reject?telegram_id={ADMIN_TG}",
        headers=BOT_HEADERS,
        json={"reason": "Возраст не сходится"},
    )
    assert rejected.status_code == 200, rejected.text

    profile = _profile(client, PLAYER_TG)
    assert profile["bio"] == "Играю с 2015 года"
    assert profile["age"] is None
    assert profile["pending_changes"] == {}


def test_moderation_is_closed_to_ordinary_players(admin):
    client, _ = admin
    register_bot_player(client, 710003, "Обычный")
    register_bot_player(client, PLAYER_TG, "Новичок")
    player_id = _player_id(PLAYER_TG)

    resp = client.post(
        f"/api/bot/moderation/registrations/{player_id}/confirm?telegram_id=710003",
        headers=BOT_HEADERS,
    )
    assert resp.status_code == 403
    assert _profile(client, PLAYER_TG)["confirmation_status"] == "pending"


def test_site_admin_without_bot_rights_can_still_decide(admin):
    """Уведомление уходит любому админу с привязанным Telegram, в том числе
    админу сайта без прав в боте, -- кнопки в нём обязаны у него работать."""
    client, _ = admin
    register_bot_player(client, 710004, "Сайтадмин")
    db = SessionLocal()
    try:
        site_admin = db.query(models.Player).filter(models.Player.telegram_id == 710004).one()
        site_admin.is_site_admin = True
        db.commit()
    finally:
        db.close()

    register_bot_player(client, PLAYER_TG, "Новичок")
    player_id = _player_id(PLAYER_TG)
    resp = client.post(
        f"/api/bot/moderation/registrations/{player_id}/confirm?telegram_id=710004",
        headers=BOT_HEADERS,
    )
    assert resp.status_code == 200, resp.text


def test_admin_notifications_reach_bot_admins_too(admin):
    """Раньше уведомление уходило только админам сайта: решение принималось
    на сайте. Теперь решают в боте -- значит, писать надо и бот-админам."""
    client, _ = admin
    _admin(client)
    register_bot_player(client, PLAYER_TG, "Новичок")

    queue = client.get("/api/bot/admin-notifications", headers=BOT_HEADERS).json()
    assert ADMIN_TG in queue["recipients"]


def test_pending_queue_lists_everything_awaiting_a_decision(admin):
    """Раздел «На проверке» в админ-меню бота.

    Не то же, что /admin-notifications: та очередь пустеет после ack'а, а
    уведомление админ может удалить из чата. Без этого списка заявка тогда не
    всплыла бы больше нигде -- экрана модерации на сайте больше нет.
    """
    client, headers = admin
    _admin(client)
    register_bot_player(client, PLAYER_TG, "Новичок")
    player_id = _player_id(PLAYER_TG)

    editor_tg = 710005
    register_bot_player(client, editor_tg, "Шериф")
    client.post(f"/api/admin/players/{_player_id(editor_tg)}/confirm", headers=headers)
    client.put(
        f"/api/bot/players/me?telegram_id={editor_tg}",
        headers=BOT_HEADERS,
        json={"bio": "Играю с 2015 года"},
    )

    def queue() -> dict:
        resp = client.get(
            "/api/bot/moderation/pending",
            headers=BOT_HEADERS,
            params={"telegram_id": ADMIN_TG},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    data = queue()
    assert player_id in [r["player_id"] for r in data["registrations"]]
    assert [c["field_label"] for c in data["profile_changes"]] == ["о себе"]

    # Уведомления разошлись и подтверждены -- очередь оповещения пуста, а этот
    # список по-прежнему показывает незакрытое.
    notifications = client.get("/api/bot/admin-notifications", headers=BOT_HEADERS).json()
    client.post(
        "/api/bot/admin-notifications/ack",
        headers=BOT_HEADERS,
        json={
            "registration_player_ids": [r["player_id"] for r in notifications["registrations"]],
            "profile_change_ids": [c["change_id"] for c in notifications["profile_changes"]],
        },
    )
    drained = client.get("/api/bot/admin-notifications", headers=BOT_HEADERS).json()
    assert drained["registrations"] == [] and drained["profile_changes"] == []
    assert player_id in [r["player_id"] for r in queue()["registrations"]]

    # Решённое из списка уходит.
    client.post(
        f"/api/bot/moderation/registrations/{player_id}/confirm?telegram_id={ADMIN_TG}",
        headers=BOT_HEADERS,
    )
    assert player_id not in [r["player_id"] for r in queue()["registrations"]]


def test_pending_queue_is_closed_to_ordinary_players(admin):
    client, _ = admin
    register_bot_player(client, 710006, "Обычный")
    resp = client.get(
        "/api/bot/moderation/pending", headers=BOT_HEADERS, params={"telegram_id": 710006}
    )
    assert resp.status_code == 403
