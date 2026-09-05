"""Валидация в админке и восстановление сессии.

Покрывает три места, каждое из которых раньше вело себя неправильно молча:
зарезервированный slug падал 500-й вместо 422, очистка необязательного поля
не сохранялась, а фильтр по датам терял целый день на границе.
"""

from __future__ import annotations

import pytest

from tests.conftest import make_players, make_tournament, make_tournament_game

# 15 марта 23:30 МСК и 16 марта 00:30 МСК -- в UTC обе даты приходятся на 15-е.
# Именно на этой паре ломался старый фильтр: он сравнивал TIMESTAMPTZ с голой
# датой в UTC и вдобавок был строго "<", то есть день "по" выпадал целиком.
GAME_LATE_ON_15TH = "2026-03-15T20:30:00Z"
GAME_EARLY_ON_16TH = "2026-03-15T21:30:00Z"

ROLES = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6


def _create_rated_game(client, headers, player_ids, starts_at, tournament_id) -> int:
    participants = [
        {"player_id": pid, "seat_number": seat, "role": role}
        for seat, (pid, role) in enumerate(zip(player_ids, ROLES), start=1)
    ]
    game = make_tournament_game(
        client, headers, tournament_id=tournament_id, starts_at=starts_at, participants=participants,
    )
    return game["id"]


@pytest.mark.parametrize(
    "slug, why",
    [
        ("admin", "зарезервирован под раздел сайта"),
        ("games", "зарезервирован под раздел сайта"),
        ("Верх", "кириллица"),
        ("a", "короче двух символов"),
        ("-dash", "начинается с дефиса"),
    ],
)
def test_invalid_slug_is_a_422_not_a_500(admin, slug, why):
    client, headers = admin
    resp = client.post(
        "/api/admin/players", json={"nickname": "Кто-то", "slug": slug}, headers=headers
    )
    assert resp.status_code == 422, f"{slug} ({why}) -> {resp.status_code}: {resp.text}"
    assert resp.json()["detail"]


def test_optional_player_fields_can_be_cleared(admin):
    client, headers = admin
    created = client.post(
        "/api/admin/players",
        json={
            "nickname": "Шеф",
            "slug": "chef",
            "full_name": "Иванов Иван Иванович",
            "age": 25,
            "bio": "давно в клубе",
            "favorite_role": "sheriff",
        },
        headers=headers,
    ).json()

    resp = client.put(
        f"/api/admin/players/{created['id']}",
        json={
            "nickname": "Шеф",
            "slug": "chef",
            "full_name": None,
            "age": None,
            "bio": None,
            "favorite_role": None,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["full_name"] is None
    assert updated["age"] is None
    assert updated["bio"] is None
    assert updated["favorite_role"] is None
    assert updated["nickname"] == "Шеф"


def test_fields_not_sent_are_left_untouched(admin):
    """Очистка -- это явный null в теле. Отсутствие ключа значит «не трогай»."""
    client, headers = admin
    created = client.post(
        "/api/admin/players",
        json={"nickname": "Шеф", "slug": "chef", "bio": "важное", "age": 30},
        headers=headers,
    ).json()

    resp = client.put(
        f"/api/admin/players/{created['id']}", json={"age": 31}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["age"] == 31
    assert resp.json()["bio"] == "важное"


def test_required_fields_cannot_be_nulled(admin):
    client, headers = admin
    created = client.post(
        "/api/admin/players", json={"nickname": "Шеф", "slug": "chef"}, headers=headers
    ).json()

    resp = client.put(
        f"/api/admin/players/{created['id']}", json={"nickname": None}, headers=headers
    )
    assert resp.status_code == 422, resp.text
    assert client.get(f"/api/admin/players/{created['id']}", headers=headers).json()["nickname"] == "Шеф"


def test_date_filter_covers_the_whole_to_day_in_club_time(admin):
    client, headers = admin
    player_ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    late_15th = _create_rated_game(client, headers, player_ids, GAME_LATE_ON_15TH, tid)
    early_16th = _create_rated_game(client, headers, player_ids, GAME_EARLY_ON_16TH, tid)

    def ids(**params):
        resp = client.get("/api/games", params=params)
        assert resp.status_code == 200, resp.text
        return {g["id"] for g in resp.json()["items"]}

    assert ids() == {late_15th, early_16th}

    # «по 15-е» включает 15-е целиком, включая игру в 23:30 МСК...
    assert ids(date_to="2026-03-15") == {late_15th}
    # ...и не захватывает игру в 00:30 МСК следующих суток, хотя в UTC у неё
    # та же календарная дата.
    assert ids(date_from="2026-03-16") == {early_16th}
    assert ids(date_from="2026-03-15", date_to="2026-03-16") == {late_15th, early_16th}
    assert ids(date_to="2026-03-14") == set()


def test_expired_access_cookie_is_recoverable_via_refresh(admin):
    """Access живёт 15 минут, refresh -- неделю. Фронт тратит refresh на первом
    401 и повторяет запрос (frontend/src/lib/api.ts); проверяем серверную
    половину этого сценария."""
    client, headers = admin
    assert client.get("/api/admin/players", headers=headers).status_code == 200

    # Ровно то, что делает браузер, когда у access-куки истекает max_age.
    client.cookies.delete("access_token")
    assert client.get("/api/admin/players", headers=headers).status_code == 401

    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 200, resp.text
    assert client.cookies.get("access_token")

    # CSRF-токен после refresh новый -- фронт перечитывает куку перед повтором.
    fresh_headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    assert client.get("/api/admin/players", headers=fresh_headers).status_code == 200
    assert client.post(
        "/api/admin/players",
        json={"nickname": "После рефреша", "slug": "after-refresh"},
        headers=fresh_headers,
    ).status_code == 200


def test_refresh_without_a_refresh_cookie_is_rejected(admin):
    client, _ = admin
    client.cookies.clear()
    assert client.post("/api/auth/refresh").status_code == 401


def test_games_can_be_filtered_by_tournament(admin):
    """Фильтр по исходу убран, вместо него -- турнир и даты."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    cup = make_tournament(client, headers, name="Кубок ВМК", slug="kubok-vmk")
    open_cup = make_tournament(client, headers, name="Открытый турнир", slug="otkrytyj")

    in_cup = _create_rated_game(client, headers, ids, "2026-04-01T18:00:00Z", cup)
    in_open = _create_rated_game(client, headers, ids, "2026-04-08T18:00:00Z", open_cup)

    def ids_for(**params):
        resp = client.get("/api/games", params=params)
        assert resp.status_code == 200, resp.text
        return {g["id"] for g in resp.json()["items"]}

    assert ids_for() == {in_cup, in_open}
    assert ids_for(tournament_slug="kubok-vmk") == {in_cup}
    assert ids_for(tournament_slug="otkrytyj") == {in_open}
    assert ids_for(tournament_slug="net-takogo") == set()

    # Турнир и даты должны фильтровать совместно.
    assert ids_for(tournament_slug="kubok-vmk", date_from="2026-04-05") == set()

    # И каждая игра несёт ссылку на свой турнир.
    items = client.get("/api/games", params={"tournament_slug": "kubok-vmk"}).json()["items"]
    assert items[0]["tournament"]["name"] == "Кубок ВМК"


def test_result_filter_is_gone(admin):
    """Параметр result больше не сужает выдачу -- фильтр по исходу убран."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    game_id = _create_rated_game(client, headers, ids, "2026-04-01T18:00:00Z", tid)

    # Игра создаётся с результатом mafia_win; запрос с противоположным исходом
    # раньше вернул бы пусто, теперь параметр просто игнорируется.
    resp = client.get("/api/games", params={"result": "city_win"})
    assert resp.status_code == 200, resp.text
    assert [g["id"] for g in resp.json()["items"]] == [game_id]


def test_site_stats_counts_games_players_and_tournaments(admin):
    """Главная страница показывает три числа. Раньше турниров среди них не
    было -- добавлены вместе с разделом "Турниры" на сайте."""
    client, headers = admin
    assert client.get("/api/stats").json() == {
        "games_count": 0,
        "players_count": 1,  # сам admin -- уже созданный игрок
        "tournaments_count": 0,
    }

    player_ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    _create_rated_game(client, headers, player_ids, "2026-05-01T18:00:00Z", tid)
    make_tournament(client, headers, name="Второй турнир", slug="vtoroj")

    stats = client.get("/api/stats").json()
    assert stats["games_count"] == 1
    assert stats["players_count"] == 11
    assert stats["tournaments_count"] == 2
