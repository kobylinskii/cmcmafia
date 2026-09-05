"""Ранг и постраничный обход таблицы рейтинга.

Оба случая ниже наблюдались на живых данных: девять игроков с одинаковым
рейтингом получали в таблице места 2..10, а на своих страницах -- каждый «#2»;
и постраничный обход той же таблицы показывал одних игроков дважды, а других
не показывал вовсе.
"""

from __future__ import annotations

from tests.conftest import make_players, make_tournament, make_tournament_game

ROLES = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6


def _rated_game(client, headers, ids, tournament_id, starts_at):
    return make_tournament_game(
        client, headers, tournament_id=tournament_id, starts_at=starts_at,
        participants=[
            {"player_id": pid, "seat_number": seat, "role": role}
            for seat, (pid, role) in enumerate(zip(ids, ROLES), start=1)
        ],
    )


def _rating(client, **params):
    resp = client.get("/api/rating", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_tied_players_share_a_rank(admin):
    """Одна игра, все проиграли одинаково -> у семерых красных один рейтинг и
    одно место. Раньше таблица нумеровала их подряд."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _rated_game(client, headers, ids, tid, "2026-02-01T18:00:00Z")

    items = _rating(client, limit=50)["items"]
    by_rating = {}
    for it in items:
        by_rating.setdefault(it["rating"], []).append(it["rank"])

    for rating, ranks in by_rating.items():
        assert len(set(ranks)) == 1, f"рейтинг {rating}: разные места {sorted(ranks)}"


def test_table_rank_matches_player_page_rank(admin):
    """Место в таблице и место на странице игрока -- одно и то же число."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _rated_game(client, headers, ids, tid, "2026-02-01T18:00:00Z")

    for row in _rating(client, limit=50)["items"]:
        page = client.get(f"/api/players/{row['slug']}")
        assert page.status_code == 200, page.text
        assert page.json()["stats"]["rank"] == row["rank"], (
            f"{row['nickname']}: в таблице #{row['rank']}, "
            f"на странице #{page.json()['stats']['rank']}"
        )


def test_paging_covers_every_player_exactly_once(admin):
    """Постраничный обход отдаёт каждого игрока ровно один раз -- даже когда
    рейтинги совпадают. Без уникального тай-брейкера в ORDER BY порядок между
    запросами не определён, и срезы OFFSET/LIMIT пересекались."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _rated_game(client, headers, ids, tid, "2026-02-01T18:00:00Z")

    total = _rating(client, limit=1)["total"]
    assert total == 10

    seen = []
    for offset in range(0, total, 3):
        seen += [it["slug"] for it in _rating(client, limit=3, offset=offset)["items"]]

    assert len(seen) == total, f"обход вернул {len(seen)} строк вместо {total}"
    assert len(set(seen)) == total, f"дубликаты между страницами: {sorted(seen)}"


def test_search_keeps_the_club_wide_rank(admin):
    """Найденный по нику игрок показывает своё место в клубе, а не номер
    строки в выдаче поиска."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _rated_game(client, headers, ids, tid, "2026-02-01T18:00:00Z")

    full = {it["slug"]: it["rank"] for it in _rating(client, limit=50)["items"]}
    target = _rating(client, limit=50)["items"][-1]

    found = _rating(client, q=target["nickname"])["items"]
    assert found, "поиск ничего не нашёл"
    assert found[0]["rank"] == full[found[0]["slug"]]
