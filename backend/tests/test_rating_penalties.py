"""Что именно из штрафов попадает в Sa, а что считается отдельно.

Числа взяты не из головы, а сверены с реальной клубной таблицей (7 игр, 70
строк, все игроки на старте 1000 и с K=40): при равных командах ожидание
E = 0.5, и дельта равна `40 * (Sa/7 - 0.5)`. Так, игрок с двумя баллами
получал в таблице ровно -8.571428, а с полутора -- ровно -11.428571.

До этой сверки ЖК и СК не входили в Sa вовсе: карточка уменьшала «Итог» в
таблице игры на сайте, но на рейтинг не влияла никак.
"""

from __future__ import annotations

import pytest

from app import models
from app.database import SessionLocal
from tests.conftest import make_players, make_tournament, make_tournament_game

ROLES = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6

# Все игроки в этих тестах играют первую игру: рейтинг 1000, K = 40, команды
# равны -> E = 0.5 у обеих. Тогда delta = K * (Sa/7 - 0.5).
K = 40
M = 7
E = 0.5


def expected_delta(sa: float, penalty: float = 0.0) -> float:
    return round(K * (sa - E * M) / M - penalty, 2)


def _game(client, headers, ids, tournament_id, first_seat_extra):
    """Игра, где место №1 (Дон, чёрные) получает переданные поля, остальные -- пустые."""
    participants = [
        {"player_id": pid, "seat_number": seat, "role": role}
        for seat, (pid, role) in enumerate(zip(ids, ROLES), start=1)
    ]
    participants[0].update(first_seat_extra)
    return make_tournament_game(
        client, headers, tournament_id=tournament_id,
        starts_at="2026-02-01T18:00:00Z", result="mafia_win",
        participants=participants,
    )


def _delta(nickname: str) -> float:
    db = SessionLocal()
    try:
        row = (
            db.query(models.PlayerRatingHistory)
            .join(models.Player, models.Player.id == models.PlayerRatingHistory.player_id)
            .filter(models.Player.nickname == nickname)
            .one()
        )
        return float(row.delta)
    finally:
        db.close()


def _sa(nickname: str) -> float:
    db = SessionLocal()
    try:
        row = (
            db.query(models.PlayerRatingHistory)
            .join(models.Player, models.Player.id == models.PlayerRatingHistory.player_id)
            .filter(models.Player.nickname == nickname)
            .one()
        )
        return float(row.sa)
    finally:
        db.close()


def test_yellow_card_lowers_the_rating(admin):
    """ЖК хранится в игровых баллах, поэтому вычитается прямо из Sa.

    2.5 за победу + 2.0 от судей - 0.5 ЖК = 4.0 -> delta = 40*(4/7 - 0.5).
    """
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _game(client, headers, ids, tid, {"points_win": 2.5, "points_judge": 2.0, "zk": 0.5})

    assert _sa("Игрок1") == pytest.approx(4.0)
    assert _delta("Игрок1") == expected_delta(4.0)


def test_soft_card_lowers_the_rating(admin):
    """СК считается так же, как ЖК."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _game(client, headers, ids, tid, {"points_win": 2.5, "points_judge": 2.0, "sk": 1.0})

    assert _sa("Игрок1") == pytest.approx(3.5)
    assert _delta("Игрок1") == expected_delta(3.5)


def test_card_costs_exactly_k_times_card_over_m(admin):
    """Цена карточки в очках рейтинга -- K * ЖК / M, то есть 2.86 при K=40.

    Тот же игрок, та же игра, разница только в карточке.
    """
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)

    _game(client, headers, ids, tid, {"points_win": 2.5, "points_judge": 2.0})
    without_card = _delta("Игрок1")

    game_id = _game(client, headers, ids, tid, {"points_win": 2.5, "points_judge": 2.0, "zk": 0.5})
    # Вторая игра тех же десятерых -- смотрим её же строку истории, поэтому
    # первую удаляем, чтобы рейтинг снова считался от 1000.
    assert client.delete(f"/api/admin/games/{game_id['id'] - 1}", headers=headers).status_code == 200
    with_card = _delta("Игрок1")

    assert without_card - with_card == pytest.approx(K * 0.5 / M, abs=0.01)


def test_removals_and_ppk_stay_out_of_sa(admin):
    """Удаления и ППК -- отдельный штраф O в очках рейтинга, а не в баллах.

    Sa остаётся «чистым», а из дельты вычитается ставка _penalty_rates
    (8 очков за удаление у игрока с меньше чем 30 играми).
    """
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _game(client, headers, ids, tid, {"points_win": 2.5, "points_judge": 2.0, "removals": 1})

    assert _sa("Игрок1") == pytest.approx(4.5), "удаление не должно попадать в Sa"
    assert _delta("Игрок1") == expected_delta(4.5, penalty=8.0)


def test_published_formula_mentions_the_cards(admin):
    """Описание формулы на сайте собирается из кода -- в нём Sa обязан
    упоминать карточки, иначе текст разойдётся с расчётом."""
    client, _ = admin
    resp = client.get("/api/rating/formula")
    assert resp.status_code == 200, resp.text
    sa_line = next(item for item in resp.json()["legend"] if item["symbol"] == "Sa")
    assert "ЖК" in sa_line["text"] and "СК" in sa_line["text"]
