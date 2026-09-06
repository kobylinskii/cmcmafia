"""Средний балл, средний доп. балл и влияние обучающих игр на рейтинг.

Раньше средний балл не вычитал ни одного штрафа, средний доп. балл ошибочно
включал Ci, а обучающие игры хоть и не двигали рейтинг напрямую, но растили
games_count -- а он задаёт коэффициент K, то есть влияли косвенно.
"""

from __future__ import annotations

import pytest

from tests.conftest import make_players, make_tournament, make_tournament_game

ROLES = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6


def _participants(player_ids, first_seat_extra=None):
    out = []
    for seat, (pid, role) in enumerate(zip(player_ids, ROLES), start=1):
        p = {"player_id": pid, "seat_number": seat, "role": role}
        if seat == 1 and first_seat_extra:
            p.update(first_seat_extra)
        out.append(p)
    return out


def _create_game(client, headers, player_ids, *, game_type="tournament",
                 tournament_id=None, starts_at="2026-02-01T18:00:00Z", extra=None):
    if game_type == "tournament":
        result = make_tournament_game(
            client, headers, tournament_id=tournament_id, starts_at=starts_at,
            participants=_participants(player_ids, extra),
        )
        return result["id"]
    body = {
        "starts_at": starts_at,
        "location": "Клуб",
        "game_type": game_type,
        "result": "mafia_win",
        "participants": _participants(player_ids, extra),
    }
    resp = client.post("/api/admin/games", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _stats(client, slug):
    resp = client.get(f"/api/players/{slug}")
    assert resp.status_code == 200, resp.text
    return resp.json()["stats"]


def test_average_score_counts_every_point_and_every_penalty(admin):
    """Средний балл = (все баллы − все штрафы) / игр.

    Без ППК: он несовместим с доп. баллами -- нарушитель по правилу остаётся
    и без судейских, и без ЛХ, так что в одной строке их не собрать. Итог
    игрока с ППК проверяется отдельно, в tests/test_ppk_rule.py.
    """
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _create_game(client, headers, ids, tournament_id=tid, extra={
        "points_win": 2.5,     # +2.5
        "points_judge": 1.0,   # +1.0
        # ЛХ бывает только у первоубиенного -- иначе баллы за него ушли бы в
        # рейтинг, но не попали в распределение ЛХ на странице игрока.
        "info": "first_killed",
        "lh": 1.5,             # 3/3 попаданий -> +1.0 балла
        "ci": 0.5,             # +0.5
        "zk": 0.5,             # -0.5
        "sk": 1.0,             # -1.0
        "removals": 2,         # -2 * 0.5 = -1.0
    })
    # 2.5 + 1.0 + 1.0 + 0.5 = 5.0 баллов;  0.5 + 1.0 + 1.0 = 2.5 штрафов
    assert _stats(client, "player1")["avg_score"] == pytest.approx(2.5, abs=0.01)


def test_average_bonus_is_judge_points_plus_lh_without_ci(admin):
    """Доп. балл -- судейские и ЛХ. Ci это компенсация, в доп. балл не входит."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _create_game(client, headers, ids, tournament_id=tid, extra={
        "points_win": 2.5, "points_judge": 0.75, "ci": 9.0,
        "info": "first_killed", "lh": 1.0,
    })
    # 0.75 судейских + 0.5 за ЛХ (2/3 попаданий). Ci=9 сюда не попадает.
    assert _stats(client, "player1")["avg_bonus"] == pytest.approx(1.25, abs=0.01)


@pytest.mark.parametrize("hits, expected_lh_points", [(0.0, 0.0), (0.5, 0.0), (1.0, 0.5), (1.5, 1.0)])
def test_lh_hits_convert_to_points(admin, hits, expected_lh_points):
    """0/3 и 1/3 не дают баллов, 2/3 -> 0.5, 3/3 -> 1."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _create_game(client, headers, ids, tournament_id=tid,
                 extra={"points_judge": 0.0, "info": "first_killed", "lh": hits})
    assert _stats(client, "player1")["avg_bonus"] == pytest.approx(expected_lh_points, abs=0.01)


def test_lh_distribution_tells_zero_hits_apart_from_one_hit(admin):
    """0/3 и 1/3 дают одинаковые баллы, но это разные события -- в
    распределении они должны лежать в разных корзинах."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    for n, hits in enumerate((0.0, 0.5, 0.5, 1.5)):
        _create_game(client, headers, ids, tournament_id=tid,
                     starts_at=f"2026-03-0{n + 1}T18:00:00Z",
                     extra={"info": "first_killed", "lh": hits})

    dist = _stats(client, "player1")["lh_distribution"]
    assert dist == {"0/3": 1, "1/3": 2, "2/3": 0, "3/3": 1}
    assert _stats(client, "player1")["first_kill_count"] == 4


def test_training_games_do_not_touch_the_rating_at_all(admin):
    """Не только дельта рейтинга, но и счётчик игр: games_count задаёт K
    (до 30 игр K=40), поэтому обучающие игры влияли на рейтинг косвенно."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _create_game(client, headers, ids, tournament_id=tid,
                 starts_at="2026-02-01T18:00:00Z", extra={"points_win": 2.5, "points_judge": 1.5})

    before = {r["slug"]: r for r in client.get("/api/rating").json()["items"]}

    _create_game(client, headers, ids, game_type="training",
                 starts_at="2026-02-08T18:00:00Z", extra={"points_win": 2.5, "points_judge": 1.5})

    after = {r["slug"]: r for r in client.get("/api/rating").json()["items"]}
    assert set(before) == set(after)
    for slug, row in before.items():
        assert after[slug]["rating"] == pytest.approx(row["rating"], abs=0.001), slug
        assert after[slug]["games_count"] == row["games_count"], slug

    # При этом обучающая игра остаётся в личной статистике игрока.
    assert _stats(client, "player1")["total_games"] == 2


def test_rating_formula_reflects_the_real_constants(admin):
    """Числа в описании формулы -- не переписанный вручную текст, а вызов
    настоящих _k_coefficient/_penalty_rates/GAME_TYPE_WEIGHT. Если пороги или
    ставки штрафов когда-нибудь поменяются, этот тест обязан заметить, что
    публичное описание с ними разошлось."""
    client, _ = admin
    resp = client.get("/api/rating/formula")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["start_rating"] == 1000.0
    assert (data["expected_score_min"], data["expected_score_max"]) == (0.3, 0.7)

    tiers = {t["condition"]: t for t in data["k_tiers"]}
    assert tiers["до 30 игр"]["k"] == 40
    assert tiers["до 30 игр"]["removal_penalty"] == 8.0
    assert tiers["до 30 игр"]["ppk_penalty"] == 15.0
    assert tiers["от 30 игр, рейтинг выше 2000"]["k"] == 10
    assert tiers["от 30 игр, рейтинг ≤ 2000"]["k"] == 20

    weights = {w["game_type"]: w for w in data["game_type_weights"]}
    assert weights["tournament"] == {"game_type": "tournament", "label": "Турнирная", "weight": 1.0, "rated": True}
    assert weights["funky"]["weight"] == 0.3
    assert weights["training"]["weight"] == 0.0
    assert weights["training"]["rated"] is False
