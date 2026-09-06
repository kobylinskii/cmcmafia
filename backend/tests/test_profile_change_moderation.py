"""Модерация правок профиля, приходящих из бота.

Смысл механики: подтверждённый игрок не переписывает молча ФИО (оно идёт в
список на пропуск) и ник (он виден в рейтинге и составах). Правка ждёт
админа, а до решения в профиле остаётся прежнее значение -- проверяется здесь
на каждом шаге, потому что «сохранилось сразу» и «сохранилось после
подтверждения» снаружи выглядят одинаково.
"""

from __future__ import annotations

from app.database import SessionLocal
from app import models
from tests.conftest import BOT_HEADERS, register_bot_player

TG = 9100


def _player_id(telegram_id: int) -> int:
    """Ручка бота отдаёт профиль без внутреннего id -- он нужен только админке."""
    db = SessionLocal()
    try:
        return db.query(models.Player).filter(models.Player.telegram_id == telegram_id).one().id
    finally:
        db.close()


def _confirmed_player(client, headers, *, telegram_id: int = TG, nickname: str = "Шериф") -> int:
    """Игрок из бота, которого админ уже подтвердил: модерация правок касается
    только таких -- см. profile_change_service.requires_moderation."""
    register_bot_player(client, telegram_id, nickname)
    player_id = _player_id(telegram_id)
    resp = client.post(f"/api/admin/players/{player_id}/confirm", headers=headers)
    assert resp.status_code == 200, resp.text
    return player_id


def _put(client, fields: dict, *, telegram_id: int = TG):
    return client.put(
        f"/api/bot/players/me?telegram_id={telegram_id}", headers=BOT_HEADERS, json=fields
    )


def _profile(client, *, telegram_id: int = TG) -> dict:
    resp = client.get(
        "/api/bot/players/me", headers=BOT_HEADERS, params={"telegram_id": telegram_id}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _queue(client, headers) -> list[dict]:
    resp = client.get("/api/admin/players/profile-changes", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_text_edit_waits_for_the_admin_and_does_not_apply_meanwhile(admin):
    client, headers = admin
    _confirmed_player(client, headers)

    assert _put(client, {"full_name": "Петров Пётр Петрович"}).status_code == 200

    profile = _profile(client)
    assert profile["full_name"] is None, "до решения админа поле меняться не должно"
    assert profile["pending_changes"] == {"full_name": "Петров Пётр Петрович"}

    queue = _queue(client, headers)
    assert len(queue) == 1
    assert queue[0]["field"] == "full_name"
    assert queue[0]["field_label"] == "ФИО"
    assert queue[0]["current_value"] is None
    assert queue[0]["new_value"] == "Петров Пётр Петрович"

    resp = client.post(
        f"/api/admin/players/profile-changes/{queue[0]['id']}/apply", headers=headers
    )
    assert resp.status_code == 200, resp.text

    profile = _profile(client)
    assert profile["full_name"] == "Петров Пётр Петрович"
    assert profile["pending_changes"] == {}
    assert _queue(client, headers) == []


def test_rejected_edit_leaves_the_old_value(admin):
    client, headers = admin
    _confirmed_player(client, headers)
    _put(client, {"bio": "Играю с 2015 года"})

    change_id = _queue(client, headers)[0]["id"]
    resp = client.post(
        f"/api/admin/players/profile-changes/{change_id}/reject",
        headers=headers,
        json={"reason": "Слишком длинно"},
    )
    assert resp.status_code == 200, resp.text

    profile = _profile(client)
    assert profile["bio"] is None
    assert profile["pending_changes"] == {}
    assert _queue(client, headers) == []


def test_button_fields_still_apply_immediately(admin):
    """Обращение, статус прохода, роли и любимая роль выбираются кнопками из
    вариантов самого бота -- проверять там нечего, а роли решают, на какие
    места пускает запись прямо сейчас."""
    client, headers = admin
    _confirmed_player(client, headers)

    resp = _put(
        client,
        {"salutation": "госпожа", "affiliation": "mgu_no_pass", "can_staff": False, "favorite_role": "don"},
    )
    assert resp.status_code == 200, resp.text

    profile = _profile(client)
    assert profile["salutation"] == "госпожа"
    assert profile["affiliation"] == "mgu_no_pass"
    assert profile["can_staff"] is False
    assert profile["favorite_role"] == "don"
    assert profile["pending_changes"] == {}
    assert _queue(client, headers) == []


def test_unconfirmed_player_edits_apply_at_once(admin):
    """Иначе отказ «поправьте ФИО и отправьте заявку заново» стал бы тупиком:
    исправление тоже ушло бы в очередь, и поправить заявку было бы нечем."""
    client, headers = admin
    register_bot_player(client, 9200, "Новичок")

    assert _put(client, {"full_name": "Иванов Иван Иванович"}, telegram_id=9200).status_code == 200

    profile = _profile(client, telegram_id=9200)
    assert profile["confirmation_status"] == "pending"
    assert profile["full_name"] == "Иванов Иван Иванович"
    assert _queue(client, headers) == []


def test_second_edit_of_the_same_field_replaces_the_first(admin):
    """Админу нужен последний вариант, а не стопка промежуточных."""
    client, headers = admin
    _confirmed_player(client, headers)

    _put(client, {"bio": "Первый вариант"})
    _put(client, {"bio": "Второй вариант"})

    queue = _queue(client, headers)
    assert len(queue) == 1
    assert queue[0]["new_value"] == "Второй вариант"


def test_edits_to_different_fields_queue_separately(admin):
    client, headers = admin
    _confirmed_player(client, headers)

    _put(client, {"full_name": "Петров Пётр Петрович", "age": 25})

    queue = _queue(client, headers)
    assert {row["field"] for row in queue} == {"full_name", "age"}
    assert _profile(client)["age"] is None

    age_change = next(row for row in queue if row["field"] == "age")
    client.post(f"/api/admin/players/profile-changes/{age_change['id']}/apply", headers=headers)

    profile = _profile(client)
    assert profile["age"] == 25, "возраст хранится строкой, но применяется числом"
    assert profile["pending_changes"] == {"full_name": "Петров Пётр Петрович"}


def test_nickname_taken_while_the_edit_waited_is_refused_on_apply(admin):
    """Очередь ничего не резервирует: ник мог занять другой человек, и без
    повторной проверки UNIQUE отдал бы 500 вместо понятного отказа."""
    client, headers = admin
    _confirmed_player(client, headers)
    _put(client, {"nickname": "Комиссар"})
    change_id = _queue(client, headers)[0]["id"]

    register_bot_player(client, 9300, "Комиссар")

    resp = client.post(f"/api/admin/players/profile-changes/{change_id}/apply", headers=headers)
    assert resp.status_code == 422
    assert "занят" in resp.json()["detail"]
    assert _profile(client)["nickname"] == "Шериф"


def test_unchanged_value_is_not_queued(admin):
    client, headers = admin
    _confirmed_player(client, headers)

    resp = _put(client, {"nickname": "Шериф"})
    assert resp.status_code == 200
    assert _queue(client, headers) == []


def test_decision_reaches_the_bot_queue_once(admin):
    """Доставка решения устроена как у заявок: сайт решает, бот забирает
    очередь опросом и подтверждает ack'ом."""
    client, headers = admin
    _confirmed_player(client, headers)
    _put(client, {"bio": "Люблю мафию"})
    change_id = _queue(client, headers)[0]["id"]
    client.post(f"/api/admin/players/profile-changes/{change_id}/apply", headers=headers)

    resp = client.get("/api/bot/players/profile-change-notifications", headers=BOT_HEADERS)
    assert resp.status_code == 200, resp.text
    queue = resp.json()
    assert len(queue) == 1
    assert queue[0]["change_id"] == change_id
    assert queue[0]["telegram_id"] == TG
    assert queue[0]["field_label"] == "о себе"
    assert queue[0]["status"] == "applied"

    ack = client.post(
        "/api/bot/players/profile-change-notifications/ack",
        headers=BOT_HEADERS,
        json={"change_ids": [change_id]},
    )
    assert ack.json() == {"marked": 1}
    assert client.get("/api/bot/players/profile-change-notifications", headers=BOT_HEADERS).json() == []


def test_rejection_carries_the_reason_to_the_player(admin):
    client, headers = admin
    _confirmed_player(client, headers)
    _put(client, {"full_name": "Сидоров Сидор Сидорович"})
    change_id = _queue(client, headers)[0]["id"]

    empty = client.post(
        f"/api/admin/players/profile-changes/{change_id}/reject", headers=headers, json={"reason": "  "}
    )
    assert empty.status_code == 422, "отказ без причины игрок увидел бы как поломку бота"

    client.post(
        f"/api/admin/players/profile-changes/{change_id}/reject",
        headers=headers,
        json={"reason": "ФИО не совпадает с документом"},
    )
    queue = client.get("/api/bot/players/profile-change-notifications", headers=BOT_HEADERS).json()
    assert queue[0]["status"] == "rejected"
    assert queue[0]["rejection_reason"] == "ФИО не совпадает с документом"


def test_history_of_decided_changes_survives(admin):
    """Строка не удаляется после решения: это и история правок, и очередь
    доставки."""
    client, headers = admin
    _confirmed_player(client, headers)
    _put(client, {"bio": "Первый"})
    change_id = _queue(client, headers)[0]["id"]
    client.post(f"/api/admin/players/profile-changes/{change_id}/apply", headers=headers)

    db = SessionLocal()
    try:
        stored = db.get(models.PlayerProfileChange, change_id)
        assert stored is not None and stored.status == "applied"
        assert stored.decided_at is not None
    finally:
        db.close()

    # Уже рассмотренную правку второй раз не применить.
    again = client.post(f"/api/admin/players/profile-changes/{change_id}/apply", headers=headers)
    assert again.status_code == 422
