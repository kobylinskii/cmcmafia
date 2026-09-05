"""Этапы турнира (сетка по олимпийской системе для >10 участников) и новый
флоу добавления турнирных игр целиком через вкладку «Турниры».

Модель: этап -- опциональная группировка игр турнира со свободным названием
("Отборочный стол 1", "Финал") и заранее объявленным числом игр (games_count),
под которое сразу создаются пустые слоты. Обычный турнир (<=10 игроков, одна
серия из N игр) этапов не заводит вообще -- слоты для него добавляются прямо
на турнир (games.stage_id остаётся NULL), и вся публичная логика работает как
раньше (см. test_tournament_standings.py). Как только у турнира появился хотя
бы один этап, КАЖДАЯ его игра обязана лежать на конкретном этапе -- иначе
таблицы снова смешают несопоставимые составы (та самая исходная проблема).

Турнирную игру больше нельзя создать одним POST в /admin/games -- сначала
заводится пустой слот (на турнире или внутри этапа), потом слот оценивается
отдельным PUT (та же общая форма, что и для игр бота). Вкладка «Игры» в
админке турнирные игры вообще не создаёт и не показывает.
"""

from __future__ import annotations

from tests.conftest import make_players, make_tournament, make_tournament_game

ROLES = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6


def _participants(player_ids, extras=None):
    extras = extras or {}
    participants = []
    for seat, (pid, role) in enumerate(zip(player_ids, ROLES), start=1):
        p = {"player_id": pid, "seat_number": seat, "role": role}
        p.update(extras.get(pid, {}))
        participants.append(p)
    return participants


def _create_stage(client, headers, tournament_id, name, games_count=1, order=None, is_final=None):
    body = {"name": name, "games_count": games_count}
    if order is not None:
        body["order"] = order
    if is_final is not None:
        body["is_final"] = is_final
    resp = client.post(f"/api/admin/tournaments/{tournament_id}/stages", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _stage_games(client, headers, tournament_id, stage_id):
    resp = client.get(f"/api/admin/tournaments/{tournament_id}/stages/{stage_id}/games", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_plain_tournament_without_stages_is_unaffected(admin):
    """Турнир из 10 игроков -- без сеток, слот добавляется прямо на турнир."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)

    make_tournament_game(client, headers, tournament_id=tid, participants=_participants(ids))

    detail = client.get("/api/tournaments/kubok-vmk").json()
    assert detail["stages"] == []
    assert len(detail["standings"]) == 10


def test_creating_a_stage_bulk_creates_the_declared_number_of_empty_slots(admin):
    client, headers = admin
    tid = make_tournament(client, headers)
    stage = _create_stage(client, headers, tid, "Отборочный стол 1", games_count=3)

    games = _stage_games(client, headers, tid, stage["id"])
    assert len(games) == 3
    assert all(g["status"] == "scheduled" and g["result"] is None for g in games)


def test_stage_slot_is_evaluated_via_the_generic_game_update_endpoint(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    stage = _create_stage(client, headers, tid, "Финал", games_count=1)
    slot = _stage_games(client, headers, tid, stage["id"])[0]

    resp = client.put(
        f"/api/admin/games/{slot['id']}",
        json={"result": "mafia_win", "participants": _participants(ids)},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    game = resp.json()
    assert game["status"] == "rated"
    assert game["stage"]["name"] == "Финал"
    assert game["tournament"]["slug"] == "kubok-vmk"

    detail = client.get("/api/tournaments/kubok-vmk").json()
    assert len(detail["stages"][0]["standings"]) == 10


def test_tournament_and_stage_linkage_is_immutable_once_the_slot_exists(admin):
    """Форма оценки не может переставить готовый слот на другой турнир/этап --
    привязка фиксируется один раз, при создании слота (см.
    game_service.update_rated_game)."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    other_tid = make_tournament(client, headers, name="Другой", slug="drugoj")
    stage = _create_stage(client, headers, tid, "Финал", games_count=1)
    other_stage = _create_stage(client, headers, other_tid, "Финал", games_count=1)
    slot = _stage_games(client, headers, tid, stage["id"])[0]

    resp = client.put(
        f"/api/admin/games/{slot['id']}",
        json={
            "result": "mafia_win",
            "participants": _participants(ids),
            "tournament_id": other_tid,
            "stage_id": other_stage["id"],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    game = resp.json()
    assert game["tournament"]["slug"] == "kubok-vmk"
    assert game["stage"]["name"] == "Финал"
    assert game["stage"]["id"] == stage["id"]


def test_more_slots_can_be_added_to_an_existing_stage(admin):
    client, headers = admin
    tid = make_tournament(client, headers)
    stage = _create_stage(client, headers, tid, "Отборочный стол 1", games_count=2)

    resp = client.post(
        f"/api/admin/tournaments/{tid}/stages/{stage['id']}/games", json={"count": 1}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1

    games = _stage_games(client, headers, tid, stage["id"])
    assert len(games) == 3


def test_more_flat_slots_can_be_added_to_a_tournament_without_stages(admin):
    client, headers = admin
    tid = make_tournament(client, headers)

    resp = client.post(f"/api/admin/tournaments/{tid}/games", json={"count": 2}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2

    resp = client.get(f"/api/admin/tournaments/{tid}/games", headers=headers)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2


def test_unevaluated_slot_can_be_deleted(admin):
    client, headers = admin
    tid = make_tournament(client, headers)
    stage = _create_stage(client, headers, tid, "Финал", games_count=1)
    slot = _stage_games(client, headers, tid, stage["id"])[0]

    resp = client.delete(f"/api/admin/games/{slot['id']}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert _stage_games(client, headers, tid, stage["id"]) == []


def test_duplicate_stage_name_in_same_tournament_is_rejected(admin):
    client, headers = admin
    tid = make_tournament(client, headers)
    _create_stage(client, headers, tid, "Финал")
    resp = client.post(
        f"/api/admin/tournaments/{tid}/stages", json={"name": "финал", "games_count": 1}, headers=headers
    )
    assert resp.status_code == 422, resp.text


def test_stage_with_only_unrated_slots_can_be_deleted(admin):
    """Пустые заготовки -- не результат, удаление этапа удаляет их вместе с
    ним (см. пояснение пользователя: "можно добавить/удалить позже")."""
    client, headers = admin
    tid = make_tournament(client, headers)
    stage = _create_stage(client, headers, tid, "Отборочный стол 1", games_count=2)

    resp = client.delete(f"/api/admin/tournaments/{tid}/stages/{stage['id']}", headers=headers)
    assert resp.status_code == 200, resp.text


def test_stage_with_a_rated_slot_cannot_be_deleted(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    stage = _create_stage(client, headers, tid, "Финал", games_count=1)
    slot = _stage_games(client, headers, tid, stage["id"])[0]
    client.put(
        f"/api/admin/games/{slot['id']}",
        json={"result": "mafia_win", "participants": _participants(ids)},
        headers=headers,
    )

    resp = client.delete(f"/api/admin/tournaments/{tid}/stages/{stage['id']}", headers=headers)
    assert resp.status_code == 422, resp.text
    assert "игр" in resp.json()["detail"].lower()


def test_each_stage_gets_its_own_standings_table(admin):
    """Ровно то, ради чего сетки завели: игрок из отборочного стола и игрок
    финала не смешиваются в одной сумме, у каждого этапа своя таблица."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    qual = _create_stage(client, headers, tid, "Отборочный стол 1", order=1)
    final = _create_stage(client, headers, tid, "Финал", order=2)

    make_tournament_game(
        client, headers, tournament_id=tid, stage_id=qual["id"], starts_at="2026-05-01T18:00:00Z",
        participants=_participants(ids, extras={ids[0]: {"points_win": 5.0}}),
    )
    make_tournament_game(
        client, headers, tournament_id=tid, stage_id=final["id"], starts_at="2026-05-08T18:00:00Z",
        participants=_participants(ids, extras={ids[0]: {"points_win": 1.0}}),
    )

    detail = client.get("/api/tournaments/kubok-vmk").json()
    assert detail["standings"] == []  # все игры разнесены по этапам, общей плоской таблицы нет
    assert [s["name"] for s in detail["stages"]] == ["Отборочный стол 1", "Финал"]

    qual_top = detail["stages"][0]["standings"][0]
    final_top = detail["stages"][1]["standings"][0]
    assert qual_top["total_score"] == 5.0
    assert final_top["total_score"] == 1.0
    # Игрок один и тот же, но суммы этапов не смешаны.
    assert qual_top["slug"] == final_top["slug"] == "player1"


def test_admin_marks_who_advances_and_public_page_reflects_it(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    stage = _create_stage(client, headers, tid, "Отборочный стол 1")
    make_tournament_game(
        client, headers, tournament_id=tid, stage_id=stage["id"], starts_at="2026-05-01T18:00:00Z",
        participants=_participants(ids),
    )

    # До отметки -- никто не помечен прошедшим.
    detail = client.get("/api/tournaments/kubok-vmk").json()
    assert all(not row["advanced"] for row in detail["stages"][0]["standings"])

    # Админ смотрит сводную (с уже проставленными -- пока пусто) и отмечает троих.
    admin_view = client.get(
        f"/api/admin/tournaments/{tid}/stages/{stage['id']}/standings", headers=headers
    ).json()
    assert all(not row["advanced"] for row in admin_view)

    top_three = [ids[0], ids[1], ids[2]]
    resp = client.put(
        f"/api/admin/tournaments/{tid}/stages/{stage['id']}/advances",
        json={"player_ids": top_three},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert sorted(resp.json()["player_ids"]) == sorted(top_three)

    detail = client.get("/api/tournaments/kubok-vmk").json()
    advanced_slugs = {row["slug"] for row in detail["stages"][0]["standings"] if row["advanced"]}
    assert advanced_slugs == {"player1", "player2", "player3"}

    # Повторная установка ЗАМЕНЯЕТ список, а не дополняет его.
    resp = client.put(
        f"/api/admin/tournaments/{tid}/stages/{stage['id']}/advances",
        json={"player_ids": [ids[3]]},
        headers=headers,
    )
    assert sorted(resp.json()["player_ids"]) == [ids[3]]
    detail = client.get("/api/tournaments/kubok-vmk").json()
    advanced_slugs = {row["slug"] for row in detail["stages"][0]["standings"] if row["advanced"]}
    assert advanced_slugs == {"player4"}


def test_advances_endpoint_rejects_unknown_player_ids(admin):
    client, headers = admin
    tid = make_tournament(client, headers)
    stage = _create_stage(client, headers, tid, "Финал")
    resp = client.put(
        f"/api/admin/tournaments/{tid}/stages/{stage['id']}/advances",
        json={"player_ids": [999999]},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_stages_ordered_by_order_field_not_creation_order(admin):
    client, headers = admin
    tid = make_tournament(client, headers)
    _create_stage(client, headers, tid, "Финал", order=2)
    _create_stage(client, headers, tid, "Отборочный стол 1", order=1)

    stages = client.get(f"/api/admin/tournaments/{tid}/stages", headers=headers).json()
    assert [s["name"] for s in stages] == ["Отборочный стол 1", "Финал"]


def test_generic_games_endpoint_always_rejects_tournament_game_type(admin):
    """Вкладка «Игры» турнирные игры больше не создаёт вообще -- единственный
    путь теперь через слот этапа/турнира (см. app.services.game_service)."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    resp = client.post(
        "/api/admin/games",
        json={
            "starts_at": "2026-05-01T18:00:00Z",
            "location": "Клуб",
            "game_type": "tournament",
            "result": "mafia_win",
            "participants": _participants(ids),
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_funky_game_cannot_be_given_a_tournament_id(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    resp = client.post(
        "/api/admin/games",
        json={
            "starts_at": "2026-05-01T18:00:00Z",
            "location": "Клуб",
            "game_type": "funky",
            "tournament_id": tid,
            "result": "mafia_win",
            "participants": _participants(ids),
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_public_page_lists_numbered_games_and_final_flag_per_stage(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    qual = _create_stage(client, headers, tid, "Отборочный стол 1", games_count=2)
    _create_stage(client, headers, tid, "Финал", games_count=1, is_final=True)

    detail = client.get("/api/tournaments/kubok-vmk").json()
    stages_by_name = {s["name"]: s for s in detail["stages"]}

    assert stages_by_name["Отборочный стол 1"]["is_final"] is False
    assert [g["number"] for g in stages_by_name["Отборочный стол 1"]["games"]] == [1, 2]
    assert all(g["status"] == "scheduled" for g in stages_by_name["Отборочный стол 1"]["games"])

    assert stages_by_name["Финал"]["is_final"] is True
    assert [g["number"] for g in stages_by_name["Финал"]["games"]] == [1]

    # Оцениваем один слот -- в публичном списке у него появляется result.
    slot = _stage_games(client, headers, tid, qual["id"])[0]
    client.put(
        f"/api/admin/games/{slot['id']}",
        json={"result": "mafia_win", "participants": _participants(ids)},
        headers=headers,
    )
    detail = client.get("/api/tournaments/kubok-vmk").json()
    games = {s["name"]: s["games"] for s in detail["stages"]}["Отборочный стол 1"]
    rated = next(g for g in games if g["id"] == slot["id"])
    assert rated["status"] == "rated"
    assert rated["result"] == "mafia_win"


def test_only_one_stage_can_be_final_at_a_time(admin):
    client, headers = admin
    tid = make_tournament(client, headers)
    stage_a = _create_stage(client, headers, tid, "Отборочный стол 1", is_final=True)
    stage_b = _create_stage(client, headers, tid, "Финал", is_final=True)

    stages = client.get(f"/api/admin/tournaments/{tid}/stages", headers=headers).json()
    by_id = {s["id"]: s for s in stages}
    assert by_id[stage_a["id"]]["is_final"] is False
    assert by_id[stage_b["id"]]["is_final"] is True


def test_marking_a_stage_final_via_update_unsets_the_previous_one(admin):
    client, headers = admin
    tid = make_tournament(client, headers)
    stage_a = _create_stage(client, headers, tid, "Отборочный стол 1", is_final=True)
    stage_b = _create_stage(client, headers, tid, "Финал")

    resp = client.put(
        f"/api/admin/tournaments/{tid}/stages/{stage_b['id']}",
        json={"is_final": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_final"] is True

    stages = client.get(f"/api/admin/tournaments/{tid}/stages", headers=headers).json()
    by_id = {s["id"]: s for s in stages}
    assert by_id[stage_a["id"]]["is_final"] is False
    assert by_id[stage_b["id"]]["is_final"] is True
