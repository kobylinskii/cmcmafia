"""Номинации турнира: лучший мирный / чёрный / дон / шериф, MVP и топ-3.

Считаются по играм финального (или единственного) стола, победителя можно
заменить вручную, а весь блок -- показать или спрятать на публичной странице.
"""

from __future__ import annotations

from tests.conftest import make_players, make_tournament, make_tournament_game

# Порядок ролей по местам за столом. Между играми состав один и тот же (этого
# требует game_service), а вот роли у людей меняются -- как и на живом турнире.
ROLES_A = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6
ROLES_B = ["mafia", "don", "sheriff", "mafia"] + ["citizen"] * 6


def _participants(player_ids, roles, extras: dict[int, dict] | None = None):
    extras = extras or {}
    out = []
    for seat, (pid, role) in enumerate(zip(player_ids, roles), start=1):
        p = {"player_id": pid, "seat_number": seat, "role": role}
        p.update(extras.get(pid, {}))
        out.append(p)
    return out


def _awards(client, headers, tid) -> dict:
    resp = client.get(f"/api/admin/tournaments/{tid}/awards", headers=headers)
    assert resp.status_code == 200, resp.text
    return {item["nomination"]: item for item in resp.json()["items"]}


def _make_two_games(client, headers, ids, tid, *, stage_id=None):
    """Две игры одного стола. Кто и что получает:

    ids[0]: дон (судейские 2.0), потом мафия      -> лучший дон
    ids[1]: мафия (1.5), потом дон (0.5)          -> лучший чёрный
    ids[3]: шериф (1.0 + ЛХ 3/3), потом мафия     -> лучший шериф
    ids[2]: мафия, потом шериф (0.5)
    ids[4]: мирный в обеих играх (1.0 в первой)   -> лучший мирный
    """
    make_tournament_game(
        client, headers, tournament_id=tid, stage_id=stage_id,
        starts_at="2026-03-01T18:00:00Z", result="city_win",
        participants=_participants(ids, ROLES_A, extras={
            ids[0]: {"points_judge": 2.0},
            ids[1]: {"points_judge": 1.5},
            ids[3]: {"points_judge": 1.0, "info": "first_killed", "lh": 1.5},
            ids[4]: {"points_judge": 1.0},
        }),
    )
    make_tournament_game(
        client, headers, tournament_id=tid, stage_id=stage_id,
        starts_at="2026-03-02T18:00:00Z", result="mafia_win",
        participants=_participants(ids, ROLES_B, extras={
            ids[1]: {"points_judge": 0.5},
            ids[2]: {"points_judge": 0.5},
        }),
    )


def test_nominations_computed_over_the_single_table(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _make_two_games(client, headers, ids, tid)

    awards = _awards(client, headers, tid)
    slug = {f"player{i}": pid for i, pid in enumerate(ids, start=1)}

    # Лучший дон -- судейские на доне / игры на доне: 2.0/1 против 0.5/1.
    don = awards["best_don"]["winner"]
    assert slug[don["slug"]] == ids[0]
    assert don["score"] == 2.0
    assert don["games_count"] == 1  # статистика -- именно на доне, а не по турниру

    # Лучший чёрный -- только мафия (дон считается отдельной номинацией):
    # ids[1] взял 1.5 за одну игру мафией, ids[0] за свою -- ноль.
    black = awards["best_mafia"]["winner"]
    assert slug[black["slug"]] == ids[1]
    assert black["score"] == 1.5

    # Лучший шериф -- судейские ПЛЮС баллы за ЛХ: (1.0 + 1.0) / 1 игру.
    sheriff = awards["best_sheriff"]["winner"]
    assert slug[sheriff["slug"]] == ids[3]
    assert sheriff["score"] == 2.0
    assert sheriff["lh_points"] == 1.0

    # Лучший мирный -- 1.0 судейских за две игры мирным, то есть 0.5 за игру.
    citizen = awards["best_citizen"]["winner"]
    assert slug[citizen["slug"]] == ids[4]
    assert citizen["score"] == 0.5
    assert citizen["games_count"] == 2

    # MVP -- судейские плюс ЛХ по всем ролям, делённые на игры. Тут ровно
    # 1.0 за игру сразу у троих (ids[0], ids[1], ids[3]), и равенство
    # разводит место в турнирной таблице -- выше всех ids[1].
    mvp = awards["mvp"]["winner"]
    assert slug[mvp["slug"]] == ids[1]
    assert mvp["score"] == 1.0
    assert mvp["games_count"] == 2  # статистика на финальном столе целиком

    # Топ-3 -- по сумме баллов таблицы. У той же тройки сумма одинаковая (2.0),
    # порядок задаёт тай-брейк: судейские (у ids[3] их меньше), затем победы на
    # активных ролях (ids[1] выиграл доном, ids[0] доном проиграл).
    places = [awards[key]["winner"] for key in ("first_place", "second_place", "third_place")]
    assert [slug[p["slug"]] for p in places] == [ids[1], ids[0], ids[3]]
    assert [p["rank"] for p in places] == [1, 2, 3]
    assert all(p["total_score"] == 2.0 for p in places)


def test_ties_are_broken_by_judge_points_then_wins(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    # Одна игра, город побеждает. У троих итог одинаковый (1.0), но:
    #   ids[4] (мирный) -- балл судейский, ПЛЮС победа красным;
    #   ids[5] (мирный) -- балл компенсацией Ci, победа красным;
    #   ids[1] (мафия)  -- балл судейский, но игру проиграл.
    make_tournament_game(
        client, headers, tournament_id=tid, result="city_win",
        participants=_participants(ids, ROLES_A, extras={
            ids[4]: {"points_judge": 1.0},
            ids[5]: {"ci": 1.0},
            ids[1]: {"points_judge": 1.0},
        }),
    )

    standings = client.get("/api/tournaments/kubok-vmk").json()["standings"]
    order = [row["slug"] for row in standings if row["total_score"] == 1.0]
    # Судейские важнее -> оба «судейских» выше игрока с Ci; из них выше тот,
    # кто выиграл.
    assert order == ["player5", "player2", "player6"]


def test_only_final_stage_counts(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    qual = client.post(
        f"/api/admin/tournaments/{tid}/stages",
        json={"name": "Отборочный стол 1", "games_count": 0 or 1},
        headers=headers,
    ).json()
    final = client.post(
        f"/api/admin/tournaments/{tid}/stages",
        json={"name": "Финал", "games_count": 1, "is_final": True},
        headers=headers,
    ).json()

    # На отборе гений -- ids[9], на финале его нет вовсе.
    make_tournament_game(
        client, headers, tournament_id=tid, stage_id=qual["id"],
        starts_at="2026-03-01T18:00:00Z", result="city_win",
        participants=_participants(ids, ROLES_A, extras={ids[9]: {"points_judge": 5.0}}),
    )
    _make_two_games(client, headers, ids, tid, stage_id=final["id"])

    body = client.get(f"/api/admin/tournaments/{tid}/awards", headers=headers).json()
    assert body["table_name"] == "Финал"
    awards = {item["nomination"]: item for item in body["items"]}
    winners = {a["winner"]["slug"] for a in awards.values() if a["winner"]}
    assert "player10" not in winners

    # Без отметки финального этапа считать не по чему -- админке возвращается
    # объяснение, а не пустой блок без причины.
    client.put(
        f"/api/admin/tournaments/{tid}/stages/{final['id']}",
        json={"is_final": False}, headers=headers,
    )
    body = client.get(f"/api/admin/tournaments/{tid}/awards", headers=headers).json()
    assert body["items"] == []
    assert "финальным" in body["problem"]


def test_manual_winner_overrides_and_is_validated(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _make_two_games(client, headers, ids, tid)

    # Заменяем лучшего дона на второго кандидата.
    resp = client.put(
        f"/api/admin/tournaments/{tid}/awards",
        json={"winners": {"best_don": "player2"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    awards = {item["nomination"]: item for item in resp.json()["items"]}
    assert awards["best_don"]["winner"]["slug"] == "player2"
    assert awards["best_don"]["manual"] is True

    # Кандидатом можно быть только сыграв эту роль на финальном столе.
    resp = client.put(
        f"/api/admin/tournaments/{tid}/awards",
        json={"winners": {"best_don": "player5"}},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text

    # null возвращает расчёт.
    resp = client.put(
        f"/api/admin/tournaments/{tid}/awards",
        json={"winners": {"best_don": None}},
        headers=headers,
    )
    awards = {item["nomination"]: item for item in resp.json()["items"]}
    assert awards["best_don"]["winner"]["slug"] == "player1"
    assert awards["best_don"]["manual"] is False


def test_awards_are_hidden_until_published(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _make_two_games(client, headers, ids, tid)

    public = client.get("/api/tournaments/kubok-vmk").json()
    assert public["awards"] == []

    client.put(f"/api/admin/tournaments/{tid}/awards", json={"published": True}, headers=headers)
    public = client.get("/api/tournaments/kubok-vmk").json()
    assert len(public["awards"]) == 8
    # Кандидаты -- только для админки: публичной странице нужен победитель.
    assert all(item["candidates"] == [] for item in public["awards"])
    assert public["awards"][0]["winner"]["nickname"]

    client.put(f"/api/admin/tournaments/{tid}/awards", json={"published": False}, headers=headers)
    assert client.get("/api/tournaments/kubok-vmk").json()["awards"] == []


def test_ci_cannot_be_negative(admin):
    """Ci -- компенсация, а не штраф: минус в неё не пролезает даже через API."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    add = client.post(f"/api/admin/tournaments/{tid}/games", json={"count": 1}, headers=headers)
    game_id = add.json()[0]["id"]
    resp = client.put(
        f"/api/admin/games/{game_id}",
        json={
            "starts_at": "2026-03-01T18:00:00Z",
            "result": "city_win",
            "participants": _participants(ids, ROLES_A, extras={ids[0]: {"ci": -1.0}}),
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
