"""Ранг и постраничный обход таблицы рейтинга.

Оба случая ниже наблюдались на живых данных: девять игроков с одинаковым
рейтингом получали в таблице места 2..10, а на своих страницах -- каждый «#2»;
и постраничный обход той же таблицы показывал одних игроков дважды, а других
не показывал вовсе.
"""

from __future__ import annotations

from tests.conftest import (
    make_players,
    make_tournament,
    make_tournament_game,
    register_bot_player,
)

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


def test_search_finds_a_player_who_has_not_played_yet(admin):
    """Поиск -- это «найди человека», а не «покажи таблицу».

    Новичок без единой сыгранной игры находится по нику: иначе его страницу на
    сайте не открыть ниоткуда. В самой таблице (запроса нет) он по-прежнему не
    показывается -- рейтинга у него ещё нет.
    """
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _rated_game(client, headers, ids, tid, "2026-02-01T18:00:00Z")

    newcomer = client.post(
        "/api/admin/players", json={"nickname": "Салага", "slug": "salaga"}, headers=headers
    )
    assert newcomer.status_code == 200, newcomer.text

    assert [it["nickname"] for it in _rating(client, q="Салага")["items"]] == ["Салага"]
    assert _rating(client, q="Салага")["items"][0]["games_count"] == 0
    # Без запроса таблица прежняя: только те, кто уже играл.
    assert _rating(client, limit=50)["total"] == 10


def test_search_still_hides_an_unconfirmed_newcomer(admin):
    """Модерация регистрации сильнее поиска: пока админ не подтвердил
    новичка, его на сайте нет вовсе -- и ссылка вела бы на 404."""
    client, _ = admin
    register_bot_player(client, 9401, "Неизвестный")
    assert _rating(client, q="Неизвестный")["total"] == 0


def test_sort_changes_order_but_not_the_rank(admin):
    """Сортировка по числу игр, проценту побед и среднему доп. баллу меняет
    ПОРЯДОК строк, а место в колонке «#» остаётся клубным -- по рейтингу."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    # Мафия выигрывает: у чёрных (места 1--3) 100% побед, у красных 0%.
    # Судейские получает один красный -- он и лучший по среднему доп. баллу.
    make_tournament_game(
        client, headers, tournament_id=tid, starts_at="2026-02-01T18:00:00Z",
        result="mafia_win",
        participants=[
            {"player_id": pid, "seat_number": seat, "role": role,
             **({"points_judge": 3.0} if pid == ids[9] else {})}
            for seat, (pid, role) in enumerate(zip(ids, ROLES), start=1)
        ],
    )

    by_rating = _rating(client, limit=50, sort="rating")["items"]
    ranks = {it["slug"]: it["rank"] for it in by_rating}

    by_win_rate = _rating(client, limit=50, sort="win_rate")["items"]
    assert by_win_rate[0]["win_rate"] == 1.0
    assert [it["win_rate"] for it in by_win_rate] == sorted(
        (it["win_rate"] for it in by_win_rate), reverse=True
    )

    by_bonus = _rating(client, limit=50, sort="avg_bonus")["items"]
    assert by_bonus[0]["slug"] == "player10"

    by_games = _rating(client, limit=50, sort="games_count")["items"]
    assert [it["games_count"] for it in by_games] == sorted(
        (it["games_count"] for it in by_games), reverse=True
    )

    # Порядок поменялся, места -- нет.
    assert [it["slug"] for it in by_win_rate] != [it["slug"] for it in by_rating]
    for row in by_win_rate + by_bonus + by_games:
        assert row["rank"] == ranks[row["slug"]]


def test_avg_bonus_is_the_same_number_in_the_table_and_on_the_player_page(admin) -> None:
    """«Средний доп. балл» считается по одним и тем же играм с обеих сторон.

    Обучающие игры в рейтинг не идут вовсе (rating_service.UNRATED_GAME_TYPES),
    и таблица рейтинга их из этой колонки исключала, а страница игрока -- нет:
    у одного игрока под одной подписью выходило 1.0 в таблице и 0.5 на его
    собственной странице. Считаются только оценённые фановые и турнирные.
    """
    client, headers = admin
    player_ids = make_players(client, headers, 10)
    tournament_id = make_tournament(client, headers)

    def roster(points_judge: float) -> list[dict]:
        # Судейские получает только первый игрок -- за ним и следим.
        return [
            {
                "player_id": player_ids[i - 1],
                "seat_number": i,
                "role": role,
                "points_judge": points_judge if i == 1 else 0,
            }
            for i, role in enumerate(ROLES, start=1)
        ]

    def add_game(game_type: str, points_judge: float, starts_at: str) -> None:
        resp = client.post(
            "/api/admin/games",
            json={
                "starts_at": starts_at,
                "game_type": game_type,
                "result": "city_win",
                "participants": roster(points_judge),
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    # Турнирная 1.0 и фановая 0.5 идут в зачёт, обучающая 0 -- нет. Считаются
    # ОБА рейтинговых формата: если бы в зачёт шли только турнирные, среднее
    # вышло бы 1.0, а если бы влезла обучающая -- 0.5.
    make_tournament_game(
        client, headers, tournament_id=tournament_id, participants=roster(1.0)
    )
    add_game("funky", 0.5, "2026-02-01T18:00:00Z")
    add_game("training", 0, "2026-02-02T18:00:00Z")

    table_row = client.get("/api/rating", params={"q": "Игрок1"}).json()["items"][0]
    page_stats = client.get(f"/api/players/{table_row['slug']}").json()["stats"]

    assert table_row["avg_bonus"] == page_stats["avg_bonus"] == 0.75
    # Соседний «средний балл» на той же карточке считается по тому же набору
    # игр -- иначе на одной странице стоят две средние величины по разным
    # играм. Баллы за победу тут нулевые, так что средний балл равен доп.
    assert page_stats["avg_score"] == 0.75
    # Обучающей игры в личной статистике нет вовсе: счётчик игр показывает те
    # же две игры, по которым посчитаны средние и рейтинг.
    assert page_stats["total_games"] == 2
    assert page_stats["rating_games_count"] == 2


def test_avg_bonus_is_blank_for_a_player_with_only_training_games(admin) -> None:
    """Игроку без единой зачётной игры доп. балл не считается вовсе.

    Не ноль, а прочерк: ноль читался бы как «судьи не дали ни балла», хотя
    игр, по которым его начисляют, у человека просто нет.
    """
    client, headers = admin
    player_ids = make_players(client, headers, 10)
    resp = client.post(
        "/api/admin/games",
        json={
            "starts_at": "2026-03-01T18:00:00Z",
            "game_type": "training",
            "result": "city_win",
            "participants": [
                {
                    "player_id": player_ids[i - 1],
                    "seat_number": i,
                    "role": role,
                    "points_judge": 2.0 if i == 1 else 0,
                }
                for i, role in enumerate(ROLES, start=1)
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # В самой таблице такого игрока нет (рейтинговых игр ноль) -- он находится
    # поиском, и обе величины у него пустые.
    table_row = client.get("/api/rating", params={"q": "Игрок1"}).json()["items"][0]
    page_stats = client.get(f"/api/players/{table_row['slug']}").json()["stats"]

    assert table_row["avg_bonus"] is None
    assert page_stats["avg_bonus"] is None
    assert page_stats["avg_score"] is None
    # Игр в статистике ноль: единственная сыгранная -- обучающая.
    assert page_stats["total_games"] == 0
