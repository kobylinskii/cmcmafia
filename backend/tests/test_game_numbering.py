"""Номер игры -- её место в хронологии, а не порядок внесения.

id игры видно везде: «Игра №14» в карточке, в подтверждении удаления, в URL
/mafia/games/{id}. Поэтому нумерация обязана читаться как нумерация: идти по
дате проведения и не иметь дыр от удалённых игр. Механика -- в
game_service.resequence_game_ids.
"""

from __future__ import annotations

from app import models
from app.database import SessionLocal

from .conftest import make_players, make_session, make_tournament


def _rated_game(client, headers, *, starts_at: str, player_ids: list[int]) -> dict:
    roles = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6
    resp = client.post(
        "/api/admin/games",
        json={
            "starts_at": starts_at,
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
    assert resp.status_code == 200, resp.text
    return resp.json()


def _sessions_by_time(client, headers, day: str) -> list[tuple[int, str]]:
    resp = client.get("/api/admin/schedule/sessions", headers=headers, params={"day": day})
    assert resp.status_code == 200, resp.text
    return [(g["id"], g["starts_at"]) for g in resp.json()]


def test_game_created_backdated_takes_the_earlier_number(admin):
    """Игра, внесённая задним числом, встаёт перед уже сыгранными позже неё."""
    client, headers = admin
    players = make_players(client, headers, 10)

    later = _rated_game(client, headers, starts_at="2026-03-10T18:00:00Z", player_ids=players)
    assert later["id"] == 1

    earlier = _rated_game(client, headers, starts_at="2026-03-01T18:00:00Z", player_ids=players)
    # Ответ на создание отдаёт уже новый номер, а не тот, что выдал SERIAL.
    assert earlier["id"] == 1

    # А игра, внесённая первой, сдвинулась на номер вперёд.
    resp = client.get("/api/admin/games/2", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["starts_at"] == later["starts_at"]


def test_participants_move_with_the_game_id(admin):
    """Перенумерация тащит за собой всё, что ссылается на игру."""
    client, headers = admin
    players = make_players(client, headers, 10)

    later = _rated_game(client, headers, starts_at="2026-03-10T18:00:00Z", player_ids=players)
    _rated_game(client, headers, starts_at="2026-03-01T18:00:00Z", player_ids=players)

    resp = client.get("/api/admin/games/2", headers=headers)
    assert resp.status_code == 200
    assert [p["player_nickname"] for p in resp.json()["participants"]] == [
        p["player_nickname"] for p in later["participants"]
    ]

    db = SessionLocal()
    try:
        # Составов ровно два по десять человек, ни одна строка не осиротела и
        # не осталась висеть на старом номере.
        assert db.query(models.GameParticipant).count() == 20
        assert {g.id for g in db.query(models.Game).all()} == {1, 2}
    finally:
        db.close()


def test_deleting_a_session_closes_the_gap_in_numbering(admin):
    """Непроведённая игра удаляется из базы целиком, а нумерация сжимается."""
    client, headers = admin

    first = make_session(client, headers, starts_at="2026-04-01T15:00:00Z", location="Клуб")
    second = make_session(client, headers, starts_at="2026-04-02T15:00:00Z", location="Клуб")
    third = make_session(client, headers, starts_at="2026-04-03T15:00:00Z", location="Клуб")
    assert [first, second, third] == [1, 2, 3]

    assert client.delete(f"/api/admin/schedule/sessions/{first}", headers=headers).status_code == 200

    db = SessionLocal()
    try:
        assert [g.id for g in db.query(models.Game).order_by(models.Game.id).all()] == [1, 2]
    finally:
        db.close()

    # Следующая созданная игра продолжает нумерацию с 3, а не с 4: последовательность
    # сбрасывается вместе с перенумерацией.
    fourth = make_session(client, headers, starts_at="2026-04-04T15:00:00Z", location="Клуб")
    assert fourth == 3


def test_moving_a_session_in_time_moves_its_number(admin):
    """Перенос игры по времени меняет и её номер -- иначе нумерация перестала
    бы совпадать с хронологией сразу после первой правки расписания."""
    client, headers = admin

    make_session(client, headers, starts_at="2026-05-01T15:00:00Z", location="Клуб")
    second = make_session(client, headers, starts_at="2026-05-02T15:00:00Z", location="Клуб")

    resp = client.put(
        f"/api/admin/schedule/sessions/{second}",
        json={"starts_at": "2026-04-01T15:00:00Z"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == 1

    assert _sessions_by_time(client, headers, "01.05.2026")[0][0] == 2


def test_tournament_slots_keep_their_order_when_dates_tie(admin):
    """У пустых слотов турнира дата одна на всех (плейсхолдер по турниру).
    Перенумерация не должна их тасовать -- иначе номера прыгали бы при каждой
    правке где-то ещё."""
    client, headers = admin
    tournament_id = make_tournament(client, headers)

    resp = client.post(
        f"/api/admin/tournaments/{tournament_id}/games", json={"count": 3}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    ids = [g["id"] for g in resp.json()]
    assert ids == [1, 2, 3]

    # Ещё одна перенумерация (её вызывает любое создание игры) порядок не меняет.
    make_session(client, headers, starts_at="2027-01-01T15:00:00Z", location="Клуб")
    resp = client.get(f"/api/admin/tournaments/{tournament_id}/games", headers=headers)
    assert [g["id"] for g in resp.json()] == ids
