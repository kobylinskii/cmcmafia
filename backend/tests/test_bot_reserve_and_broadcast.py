"""Две механики бота, живущие целиком в API: авто-резерв и анонс игр.

Резерв перестал быть отдельным действием: первые max_players занимают места за
столом, все следующие тем же запросом уходят в очередь. Анонс -- обратная
задача: собрать игры недели и вычесть из клуба тех, кому он уже не нужен.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app import models
from tests.conftest import BOT_HEADERS, make_bot_admin, register_bot_player

ADMIN_TG = 777


def _create_session(client, *, max_players: int = 10, days_ahead: int = 1, hours_ahead: int = 0) -> int:
    starts_at = datetime.now(timezone.utc) + timedelta(days=days_ahead, hours=hours_ahead)
    resp = client.post(
        f"/api/bot/admin/sessions?telegram_id={ADMIN_TG}",
        headers=BOT_HEADERS,
        json={
            "starts_at": starts_at.isoformat(),
            "location": "Клуб",
            "game_type": "funky",
            "max_players": max_players,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _register(client, session_id: int, tg_id: int, role_kind: str = "player") -> dict:
    resp = client.post(
        f"/api/bot/sessions/{session_id}/register?telegram_id={tg_id}",
        headers=BOT_HEADERS,
        json={"telegram_id": tg_id, "role_kind": role_kind},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _make_players(client, telegram_ids: list[int]) -> None:
    for index, tg_id in enumerate(telegram_ids, start=1):
        register_bot_player(client, tg_id, f"Игрок{index}")


# ------------------------------------------------------------------ резерв
def test_first_ten_take_the_table_and_the_rest_queue_up(admin):
    client, _ = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client)
    telegram_ids = list(range(1001, 1013))
    _make_players(client, telegram_ids)

    for tg_id in telegram_ids[:10]:
        body = _register(client, session_id, tg_id)
        assert body["ok"] is True and body["is_reserve"] is False
        assert body["role"] == "player"

    # Одиннадцатый и двенадцатый: отказа нет, есть номер в очереди.
    eleventh = _register(client, session_id, telegram_ids[10])
    twelfth = _register(client, session_id, telegram_ids[11])
    assert (eleventh["ok"], eleventh["is_reserve"], eleventh["reserve_position"]) == (True, True, 1)
    assert (twelfth["ok"], twelfth["is_reserve"], twelfth["reserve_position"]) == (True, True, 2)

    session = client.get(
        f"/api/bot/sessions/{session_id}?telegram_id={telegram_ids[0]}", headers=BOT_HEADERS
    ).json()
    assert (session["players"], session["reserves"]) == (10, 2)


def test_queue_moves_up_in_order_when_a_seat_frees(admin):
    """Очередь именно очередь: место занимает первый вставший, а не последний."""
    client, _ = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client, max_players=2)
    telegram_ids = [2001, 2002, 2003, 2004]
    _make_players(client, telegram_ids)

    for tg_id in telegram_ids[:2]:
        _register(client, session_id, tg_id)
    _register(client, session_id, 2003)
    _register(client, session_id, 2004)

    resp = client.delete(
        f"/api/bot/sessions/{session_id}/registration?telegram_id=2001", headers=BOT_HEADERS
    )
    assert resp.json()["promoted_telegram_id"] == 2003

    mine = client.get(
        "/api/bot/registrations/mine", headers=BOT_HEADERS, params={"telegram_id": 2004}
    ).json()
    assert [(r["role"], r["is_reserve"]) for r in mine] == [("reserve", True)]


def test_staff_has_no_queue(admin):
    """Ведущий один, судей двое, и заменить их из очереди некем -- поэтому
    штаб по-прежнему отвечает честным отказом, а не резервом."""
    client, _ = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client)
    telegram_ids = [3001, 3002, 3003, 3004]
    _make_players(client, telegram_ids)

    for tg_id in telegram_ids[:3]:
        assert _register(client, session_id, tg_id, "staff")["ok"] is True

    fourth = _register(client, session_id, 3004, "staff")
    assert fourth["ok"] is False
    assert fourth["reason"] == "role_full"


# ---------------------------------------------------------------- рассылка
def _broadcast(client, days: int = 7) -> dict:
    resp = client.get(
        "/api/bot/admin/broadcast/weekly",
        headers=BOT_HEADERS,
        params={"telegram_id": ADMIN_TG, "days": days},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_announcement_covers_the_week_and_skips_everyone_already_signed_up(admin):
    client, _ = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    soon_id = _create_session(client, days_ahead=2)
    _create_session(client, days_ahead=3)
    far_id = _create_session(client, days_ahead=20)

    _make_players(client, [4001, 4002, 4003])
    _register(client, soon_id, 4001)  # в основном составе на игру недели
    _register(client, far_id, 4002)  # записан, но за пределами окна

    payload = _broadcast(client)
    assert payload["days"] == 7
    # Игра через 20 дней в анонс недели не идёт.
    assert far_id not in [game["id"] for game in payload["games"]]
    assert len(payload["games"]) == 2

    recipients = {r["telegram_id"] for r in payload["recipients"]}
    assert 4001 not in recipients, "уже записанным анонс не нужен"
    assert {4002, 4003} <= recipients


def test_reserve_counts_as_signed_up_and_rejected_players_are_skipped(admin):
    client, _ = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client, max_players=2, days_ahead=2)
    _make_players(client, [5001, 5002, 5003, 5004])

    _register(client, session_id, 5001)
    _register(client, session_id, 5004)
    reserved = _register(client, session_id, 5002)
    assert reserved["is_reserve"] is True

    db = SessionLocal()
    try:
        rejected = db.query(models.Player).filter(models.Player.telegram_id == 5003).one()
        rejected.confirmation_status = models.ConfirmationStatus.rejected.value
        # Причина обязательна на уровне БД: отказ без объяснения игрок увидеть
        # не должен (ck_players_rejected_has_reason).
        rejected.rejection_reason = "ФИО не совпадает с документом"
        db.commit()
    finally:
        db.close()

    recipients = {r["telegram_id"] for r in _broadcast(client)["recipients"]}
    assert 5001 not in recipients
    assert 5002 not in recipients, "стоящий в очереди про эти игры уже знает"
    assert 5003 not in recipients, "отклонённому сначала нужно поправить анкету"


def test_closed_registration_drops_the_game_from_the_announcement(admin):
    """Под анонсом висит кнопка «Записаться» -- игра с закрытой записью привела
    бы человека к отказу."""
    client, _ = admin
    make_bot_admin(ADMIN_TG, nickname="БотАдмин", slug="bot-admin")
    session_id = _create_session(client, days_ahead=2)
    _make_players(client, [6001])

    resp = client.put(
        f"/api/bot/admin/sessions/{session_id}?telegram_id={ADMIN_TG}",
        headers=BOT_HEADERS,
        json={"registration_until": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()},
    )
    assert resp.status_code == 200, resp.text

    assert _broadcast(client)["games"] == []
