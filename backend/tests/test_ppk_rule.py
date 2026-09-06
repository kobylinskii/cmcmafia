"""ППК: поражение по причине нарушения.

Победа присуждается команде соперников, нарушитель остаётся без
дополнительных баллов и получает штраф 2.5 балла, карточки считаются сверх
того. Правило меняет ИСХОД игры, а от исхода зависят и рейтинг Эло, и
статистика побед каждого участника -- поэтому проверяется на сервере, а не
только в форме.
"""

from __future__ import annotations

import pytest

from app.services import stats_service
from tests.conftest import make_players, make_tournament

ROLES = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6


def _participants(player_ids, patch=None):
    out = []
    for seat, (pid, role) in enumerate(zip(player_ids, ROLES), start=1):
        p = {"player_id": pid, "seat_number": seat, "role": role}
        if patch and seat in patch:
            p.update(patch[seat])
        out.append(p)
    return out


def _post(client, headers, participants, result):
    return client.post("/api/admin/games", json={
        "starts_at": "2026-02-01T18:00:00Z", "location": "Клуб",
        "game_type": "funky", "result": result, "participants": participants,
    }, headers=headers)


def test_ppk_by_black_awards_the_win_to_the_city(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    # место 1 -- дон, чёрный: победа уходит городу
    assert _post(client, headers, _participants(ids, {1: {"ppk": True}}), "city_win").status_code == 200


def test_ppk_by_black_with_a_mafia_win_is_rejected(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    resp = _post(client, headers, _participants(ids, {1: {"ppk": True}}), "mafia_win")
    assert resp.status_code == 422
    assert "городу" in resp.json()["detail"]


def test_ppk_by_red_awards_the_win_to_the_mafia(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    # место 4 -- шериф, красный: победа уходит мафии
    assert _post(client, headers, _participants(ids, {4: {"ppk": True}}), "mafia_win").status_code == 200

    resp = _post(client, headers, _participants(ids, {4: {"ppk": True}}), "city_win")
    assert resp.status_code == 422
    assert "мафии" in resp.json()["detail"]


def test_ppk_draw_is_rejected(admin):
    """Ничьей при ППК не бывает: победа присуждается соперникам."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    assert _post(client, headers, _participants(ids, {1: {"ppk": True}}), "draw").status_code == 422


def test_only_one_ppk_per_game(admin):
    client, headers = admin
    ids = make_players(client, headers, 10)
    resp = _post(client, headers, _participants(ids, {1: {"ppk": True}, 4: {"ppk": True}}), "city_win")
    assert resp.status_code == 422
    assert "только у одного" in resp.json()["detail"]


def test_offender_gets_no_extra_points(admin):
    """«0 доп баллов»: ни судейских, ни за ЛХ."""
    client, headers = admin
    ids = make_players(client, headers, 10)

    judged = _post(client, headers,
                   _participants(ids, {1: {"ppk": True, "points_judge": 0.5}}), "city_win")
    assert judged.status_code == 422
    assert "от судей" in judged.json()["detail"]

    lh = _post(client, headers,
               _participants(ids, {1: {"ppk": True, "info": "first_killed", "lh": 1.5}}), "city_win")
    assert lh.status_code == 422
    assert "ЛХ" in lh.json()["detail"]


def test_offender_score_is_the_penalty_plus_cards(admin):
    """Итог нарушителя: −2.5 за ППК, плюс ЖК и СК сверх того. Остальные баллы
    у прочих игроков считаются как обычно."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    game = _post(client, headers, _participants(ids, {
        1: {"ppk": True, "zk": 0.5, "sk": 1.0},
        5: {"points_win": 2.5, "points_judge": 1.0},
    }), "city_win").json()

    by_seat = {p["seat_number"]: p for p in
               client.get(f"/api/games/{game['id']}").json()["participants"]}

    offender = by_seat[1]
    assert offender["ppk"] is True
    # 0 баллов − (2.5 ППК + 0.5 ЖК + 1.0 СК)
    assert stats_service.SCORE_PENALTY_PPK == 2.5
    expected = 0 - (stats_service.SCORE_PENALTY_PPK + 0.5 + 1.0)
    got = (offender["points_win"] + offender["points_judge"] + (offender["ci"] or 0)
           - stats_service.SCORE_PENALTY_PPK - (offender["zk"] or 0) - (offender["sk"] or 0))
    assert got == pytest.approx(expected), f"итог нарушителя {got}, ожидалось {expected}"

    winner = by_seat[5]
    assert winner["points_win"] == 2.5
    assert winner["points_judge"] == 1.0


def _stage_slots(client, headers, games_count=2):
    """Турнир с этапом и пустыми слотами. Турнирная игра создаётся ТОЛЬКО так,
    а оценивается через PUT -- отдельный от POST путь, и правило ППК должно
    действовать на нём тоже."""
    t = client.post("/api/admin/tournaments", json={
        "name": "Турнир ППК", "slug": "t-ppk",
        "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-01-05T00:00:00Z",
    }, headers=headers).json()
    stage = client.post(f"/api/admin/tournaments/{t['id']}/stages", json={
        "name": "Этап 1", "order": 1, "games_count": games_count,
    }, headers=headers).json()
    return client.get(
        f"/api/admin/tournaments/{t['id']}/stages/{stage['id']}/games", headers=headers
    ).json()


def _rate(client, headers, game_id, participants, result):
    return client.put(f"/api/admin/games/{game_id}", json={
        "starts_at": "2026-01-02T18:00:00Z", "result": result, "participants": participants,
    }, headers=headers)


def test_ppk_rule_applies_when_rating_a_tournament_slot(admin):
    """Регрессия: проверка ППК стояла только на создании игры, а турнирные
    игры создаются пустым слотом и оцениваются через PUT -- то есть для
    турниров правило не срабатывало вообще."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    slots = _stage_slots(client, headers)

    # ППК у чёрного -- победа присуждается городу, значит mafia_win нельзя.
    refused = _rate(client, headers, slots[0]["id"],
                    _participants(ids, {1: {"ppk": True}}), "mafia_win")
    assert refused.status_code == 422, refused.text
    assert "победа присуждается" in refused.json()["detail"].lower()

    ok = _rate(client, headers, slots[0]["id"],
               _participants(ids, {1: {"ppk": True}}), "city_win")
    assert ok.status_code == 200, ok.text


def test_offender_extra_points_are_refused_on_the_update_path_too(admin):
    """Нарушитель без доп. баллов -- и при оценке турнирного слота тоже."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    slots = _stage_slots(client, headers)

    judged = _rate(client, headers, slots[0]["id"],
                   _participants(ids, {1: {"ppk": True, "points_judge": 0.5}}), "city_win")
    assert judged.status_code == 422
    assert "дополнительных баллов" in judged.json()["detail"]

    with_lh = _rate(client, headers, slots[0]["id"],
                    _participants(ids, {1: {"ppk": True, "info": "first_killed", "lh": 1.5}}),
                    "city_win")
    assert with_lh.status_code == 422
    assert "ЛХ" in with_lh.json()["detail"]
