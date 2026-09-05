"""Проверки состава игры, которых раньше не было.

Каждая из них закрывает случай, который сохранялся молча и портил цифры уже
где-то дальше -- в реплее рейтинга или в статистике игрока.
"""

from __future__ import annotations

from tests.conftest import make_players, make_tournament

ROLES = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6


def _participants(player_ids, roles=None, patch=None):
    roles = roles or ROLES
    out = []
    for seat, (pid, role) in enumerate(zip(player_ids, roles), start=1):
        p = {"player_id": pid, "seat_number": seat, "role": role}
        if patch and seat in patch:
            p.update(patch[seat])
        out.append(p)
    return out


def _post_game(client, headers, participants, game_type="funky"):
    return client.post(
        "/api/admin/games",
        json={
            "starts_at": "2026-02-01T18:00:00Z",
            "location": "Клуб",
            "game_type": game_type,
            "result": "mafia_win",
            "participants": participants,
        },
        headers=headers,
    )


def test_canonical_roster_is_accepted(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    assert _post_game(client, headers, _participants(ids)).status_code == 200


def test_all_citizens_is_rejected(admin):
    """Игра без чёрных сохранялась молча, а потом в реплее рейтинга средний
    рейтинг несуществующей команды подставлялся как START_RATING."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    resp = _post_game(client, headers, _participants(ids, roles=["citizen"] * 10))
    assert resp.status_code == 422
    assert "1 дон, 2 мафии, 1 шериф, 6 мирных" in resp.json()["detail"]


def test_two_dons_is_rejected(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    roles = ["don", "don", "mafia", "sheriff"] + ["citizen"] * 6
    resp = _post_game(client, headers, _participants(ids, roles=roles))
    assert resp.status_code == 422


def test_two_first_killed_is_rejected(admin):
    """Первоубиенный в игре ровно один."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    resp = _post_game(
        client, headers,
        _participants(ids, patch={
            1: {"info": "first_killed"},
            2: {"info": "first_killed"},
        }),
    )
    assert resp.status_code == 422
    assert "Первоубиенный" in resp.json()["detail"]


def test_lh_without_first_killed_is_rejected(admin):
    """ЛХ у не-первоубиенного давал баллы в рейтинг и в средний балл, но не
    попадал в распределение ЛХ на странице игрока -- две страницы переставали
    сходиться без видимой причины."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    resp = _post_game(client, headers, _participants(ids, patch={3: {"lh": 1.5}}))
    assert resp.status_code == 422
    assert "первоубиенного" in resp.json()["detail"]


def test_lh_on_the_first_killed_is_accepted(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    resp = _post_game(
        client, headers,
        _participants(ids, patch={1: {"info": "first_killed", "lh": 1.5}}),
    )
    assert resp.status_code == 200


def test_lh_off_the_scale_is_rejected(admin):
    """Шкала ЛХ -- четыре ступени. 0.75 раньше молча превращалось в ноль
    баллов и не попадало ни в одну корзину распределения."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    resp = _post_game(
        client, headers,
        _participants(ids, patch={1: {"info": "first_killed", "lh": 0.75}}),
    )
    assert resp.status_code == 422
