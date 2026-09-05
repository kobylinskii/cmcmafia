"""Турнирная таблица: суммы игровых колонок по всем играм турнира, один игрок
-- одна строка, отсортировано по итоговой сумме баллов.
"""

from __future__ import annotations

from tests.conftest import make_players, make_tournament, make_tournament_game

ROLES = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6


def _participants(player_ids, extras: dict[int, dict] | None = None):
    extras = extras or {}
    participants = []
    for seat, (pid, role) in enumerate(zip(player_ids, ROLES), start=1):
        p = {"player_id": pid, "seat_number": seat, "role": role}
        p.update(extras.get(pid, {}))
        participants.append(p)
    return participants


def _standings(client, slug):
    resp = client.get(f"/api/tournaments/{slug}")
    assert resp.status_code == 200, resp.text
    return resp.json()["standings"]


def test_standings_sum_across_games_and_sort_by_total_score(admin):
    client, headers = admin
    # Одна таблица турнира -- один и тот же состав из 10 во всех её играх
    # (см. game_service._validate_tournament_roster_consistency): проверяем,
    # что суммы по игроку накапливаются по обеим играм, а не берутся из
    # последней.
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)

    make_tournament_game(
        client, headers, tournament_id=tid, starts_at="2026-02-01T18:00:00Z",
        participants=_participants(
            ids,
            extras={
                ids[0]: {"points_win": 5.0},
                ids[1]: {"points_judge": 1.0},
            },
        ),
    )
    make_tournament_game(
        client, headers, tournament_id=tid, starts_at="2026-02-08T18:00:00Z",
        participants=_participants(
            ids,
            extras={
                ids[1]: {"points_judge": 1.0},  # второе появление -- должно сложиться
                ids[9]: {"ci": 3.0},
            },
        ),
    )

    standings = _standings(client, "kubok-vmk")
    by_id = {}
    slug_to_id = {f"player{i}": pid for i, pid in enumerate(ids, start=1)}
    for row in standings:
        by_id[slug_to_id[row["slug"]]] = row

    # Суммы посчитаны верно, и у всех games_count == 2 (одна и та же таблица)...
    assert by_id[ids[0]]["total_score"] == 5.0
    assert by_id[ids[1]]["total_score"] == 2.0
    assert by_id[ids[1]]["points_judge"] == 2.0
    assert by_id[ids[9]]["total_score"] == 3.0
    for pid in ids:
        assert by_id[pid]["games_count"] == 2
    # ...остальные (участвуют в обеих играх без бонусов) на нуле.
    for pid in ids[2:9]:
        assert by_id[pid]["total_score"] == 0.0

    # ...и таблица отсортирована по убыванию итоговой суммы.
    scores = [row["total_score"] for row in standings]
    assert scores == sorted(scores, reverse=True)
    assert [row["slug"] for row in standings[:3]] == ["player1", "player10", "player2"]


def test_tournament_game_rejects_a_different_roster_than_the_table_already_has(admin):
    client, headers = admin
    ids = make_players(client, headers, 11)
    tid = make_tournament(client, headers)

    make_tournament_game(
        client, headers, tournament_id=tid, starts_at="2026-02-01T18:00:00Z",
        participants=_participants(ids[0:10]),
    )
    add_resp = client.post(f"/api/admin/tournaments/{tid}/games", json={"count": 1}, headers=headers)
    slot_id = add_resp.json()[0]["id"]

    # Второй слот той же таблицы -- другой состав (ids[10] вместо ids[0]).
    resp = client.put(
        f"/api/admin/games/{slot_id}",
        json={"result": "mafia_win", "participants": _participants([*ids[1:10], ids[10]])},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "состав" in resp.json()["detail"].lower()


def test_standings_do_not_leak_across_tournaments(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid_a = make_tournament(client, headers, name="Кубок А", slug="kubok-a")
    tid_b = make_tournament(client, headers, name="Кубок Б", slug="kubok-b")

    make_tournament_game(
        client, headers, tournament_id=tid_a, starts_at="2026-03-01T18:00:00Z",
        participants=_participants(ids, extras={ids[0]: {"points_win": 4.0}}),
    )

    standings_a = _standings(client, "kubok-a")
    standings_b = _standings(client, "kubok-b")

    assert len(standings_a) == 10
    assert standings_b == []


def test_removals_and_ppk_are_penalised_and_summed(admin):
    """Итог считается по той же формуле, что и колонка «Итог» в карточке игры:
    баллы минус штрафы (ЖК, СК, удаления*0.5, ППК*1.0)."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)

    make_tournament_game(
        client, headers, tournament_id=tid, starts_at="2026-04-01T18:00:00Z",
        participants=_participants(
            ids,
            extras={
                ids[0]: {
                    "points_win": 2.5, "points_judge": 1.0, "ci": 0.5,
                    "info": "first_killed", "lh": 1.5,
                    "removals": 2, "ppk": True, "zk": 0.5, "sk": 0.0,
                },
            },
        ),
    )

    standings = {row["slug"]: row for row in _standings(client, "kubok-vmk")}
    row = standings["player1"]
    # баллы: 2.5 + 1.0 + 1.0(3/3 ЛХ) + 0.5 = 5.0; штрафы: 0.5 + 0 + 2*0.5 + 1.0 = 2.5
    assert row["total_score"] == 2.5
    assert row["ppk_count"] == 1
    assert row["removals"] == 2
    assert row["zk"] == 0.5
