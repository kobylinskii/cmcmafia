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


def _tournament_with_stage(client, headers, games_count=2):
    t = client.post("/api/admin/tournaments", json={
        "name": "Турнир состава", "slug": "t-roster",
        "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-01-05T00:00:00Z",
    }, headers=headers).json()
    stage = client.post(f"/api/admin/tournaments/{t['id']}/stages", json={
        "name": "Этап 1", "order": 1, "games_count": games_count,
    }, headers=headers).json()
    games = client.get(
        f"/api/admin/tournaments/{t['id']}/stages/{stage['id']}/games", headers=headers
    ).json()
    return t, stage, games


def _rate(client, headers, game_id, player_ids, *, result="city_win", allow=False):
    body = {
        "starts_at": "2026-01-02T18:00:00Z",
        "result": result,
        "participants": _participants(player_ids),
    }
    if allow:
        body["allow_roster_change"] = True
    return client.put(f"/api/admin/games/{game_id}", json=body, headers=headers)


def test_first_rated_game_roster_is_editable(admin):
    """Пока в таблице оценена только одна игра, её состав правится свободно."""
    client, headers = admin
    ids = make_players(client, headers, 12)
    _, _, games = _tournament_with_stage(client, headers)

    assert _rate(client, headers, games[0]["id"], ids[:10]).status_code == 200
    assert _rate(client, headers, games[0]["id"], ids[:9] + [ids[10]]).status_code == 200


def test_roster_change_is_refused_but_offers_an_override(admin):
    """Когда в таблице есть вторая оценённая игра, смена состава в первой
    отклоняется кодом ROSTER_MISMATCH -- по нему форма показывает подтверждение."""
    client, headers = admin
    ids = make_players(client, headers, 12)
    _, _, games = _tournament_with_stage(client, headers)

    assert _rate(client, headers, games[0]["id"], ids[:10]).status_code == 200
    assert _rate(client, headers, games[1]["id"], ids[:10], result="mafia_win").status_code == 200

    refused = _rate(client, headers, games[0]["id"], ids[:9] + [ids[10]])
    assert refused.status_code == 422
    assert "ROSTER_MISMATCH" in refused.json()["detail"]


def test_roster_change_goes_through_with_explicit_permission(admin):
    """С подтверждением та же правка сохраняется -- админ исправляет ошибку в
    уже внесённой игре, не удаляя следующие."""
    client, headers = admin
    ids = make_players(client, headers, 12)
    _, _, games = _tournament_with_stage(client, headers)

    assert _rate(client, headers, games[0]["id"], ids[:10]).status_code == 200
    assert _rate(client, headers, games[1]["id"], ids[:10], result="mafia_win").status_code == 200

    ok = _rate(client, headers, games[0]["id"], ids[:9] + [ids[10]], allow=True)
    assert ok.status_code == 200, ok.text
