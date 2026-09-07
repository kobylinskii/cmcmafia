"""CRUD турнира: чтение, правка, удаление и подсказка slug'а.

Сетки этапов и сводные таблицы проверяются в test_tournament_stages.py /
test_tournament_standings.py -- там же и создание турнира. Здесь ровно то,
что оставалось непокрытым: сам жизненный цикл карточки турнира. Удаление тут
самое важное: оно каскадом уносит неоценённые слоты этапов и следом
перенумеровывает ВСЕ игры клуба (см. game_service.resequence_game_ids).
"""

from __future__ import annotations

from tests.conftest import make_players, make_tournament, make_tournament_game


def _roster(player_ids: list[int]) -> list[dict]:
    roles = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6
    return [
        {"player_id": pid, "seat_number": i + 1, "role": roles[i], "points_win": 0}
        for i, pid in enumerate(player_ids)
    ]


def test_tournament_card_is_readable_by_id(admin):
    client, headers = admin
    tid = make_tournament(client, headers)

    resp = client.get(f"/api/admin/tournaments/{tid}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Кубок ВМК"
    assert body["slug"] == "kubok-vmk"
    # games_count здесь -- «оценённых игр», как и во всех остальных ручках
    # этого файла роутера.
    assert body["games_count"] == 0

    assert client.get("/api/admin/tournaments/9999", headers=headers).status_code == 404


def test_tournament_fields_are_editable(admin):
    client, headers = admin
    tid = make_tournament(client, headers)

    resp = client.put(
        f"/api/admin/tournaments/{tid}",
        json={"name": "Кубок ВМК 2026", "location": "ауд. 685"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Кубок ВМК 2026"
    assert resp.json()["location"] == "ауд. 685"
    # Не переданное поле остаётся прежним (роутер шлёт exclude_unset).
    assert resp.json()["slug"] == "kubok-vmk"


def test_tournament_update_refuses_a_duplicate_name_and_empty_required_field(admin):
    client, headers = admin
    first = make_tournament(client, headers)
    make_tournament(client, headers, name="Весенний кубок", slug="spring-cup")

    # Занятое имя -- у другого турнира, регистр при сверке не важен.
    resp = client.put(
        f"/api/admin/tournaments/{first}", json={"name": "весенний КУБОК"}, headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Турнир с таким названием уже есть"

    # Своё же имя переприсвоить можно -- exclude_id работает.
    resp = client.put(f"/api/admin/tournaments/{first}", json={"name": "Кубок ВМК"}, headers=headers)
    assert resp.status_code == 200, resp.text

    resp = client.put(f"/api/admin/tournaments/{first}", json={"name": None}, headers=headers)
    assert resp.status_code == 422
    assert "нельзя оставить пустым" in resp.json()["detail"]


def test_tournament_update_refuses_an_inverted_date_range(admin):
    client, headers = admin
    tid = make_tournament(client, headers)
    # Частичная правка сверяется с тем, что реально окажется в базе: конец
    # переносится раньше уже сохранённого начала.
    resp = client.put(
        f"/api/admin/tournaments/{tid}",
        json={"ends_at": "2024-01-01T00:00:00+00:00"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_empty_tournament_is_deleted_with_its_stages_and_slots(admin):
    """Удаление уносит пустые слоты этапов и сжимает нумерацию игр."""
    client, headers = admin
    tid = make_tournament(client, headers)
    stage = client.post(
        f"/api/admin/tournaments/{tid}/stages",
        json={"name": "Квалификация", "games_count": 3},
        headers=headers,
    ).json()
    assert len(client.get(
        f"/api/admin/tournaments/{tid}/stages/{stage['id']}/games", headers=headers
    ).json()) == 3

    resp = client.delete(f"/api/admin/tournaments/{tid}", headers=headers)
    assert resp.status_code == 200, resp.text

    assert client.get(f"/api/admin/tournaments/{tid}", headers=headers).status_code == 404
    assert client.get("/api/admin/tournaments", headers=headers).json() == []
    # Слоты уехали вместе с этапом, дыр в нумерации не осталось.
    assert client.get("/api/admin/games", headers=headers).json()["total"] == 0


def test_tournament_with_rated_games_is_not_deleted(admin):
    """Оценённые игры молча не пропадают: отказ, а не каскад."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    game = make_tournament_game(client, headers, tournament_id=tid, participants=_roster(ids))

    resp = client.delete(f"/api/admin/tournaments/{tid}", headers=headers)
    assert resp.status_code == 422
    assert "оценённых игр: 1" in resp.json()["detail"]

    # Ни турнир, ни игра не пострадали.
    assert client.get(f"/api/admin/tournaments/{tid}", headers=headers).status_code == 200
    assert client.get(f"/api/games/{game['id']}").status_code == 200


def test_slug_suggestions_are_free_and_unique(admin):
    """Подсказка slug'а -- и для турнира, и для игрока: второй раз то же имя
    должно дать уже другой slug, иначе форма предложит занятый."""
    client, headers = admin

    resp = client.get(
        "/api/admin/tournaments/slug-suggestion", params={"name": "Кубок ВМК"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    suggested = resp.json()["slug"]
    assert suggested == "kubok-vmk"

    make_tournament(client, headers, name="Кубок ВМК", slug=suggested)
    second = client.get(
        "/api/admin/tournaments/slug-suggestion", params={"name": "Кубок ВМК"}, headers=headers
    ).json()["slug"]
    assert second != suggested

    resp = client.get(
        "/api/admin/players/slug-suggestion", params={"nickname": "Барон"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    player_slug = resp.json()["slug"]
    # Подсказка обязана быть пригодной: создаём игрока ровно с ней.
    assert client.post(
        "/api/admin/players", json={"nickname": "Барон", "slug": player_slug}, headers=headers
    ).status_code == 200


def test_public_tournament_list_counts_only_rated_games(admin):
    """Публичный список турниров: имя, место и число ОЦЕНЁННЫХ игр."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)

    assert client.get("/api/tournaments").json() == [
        {"slug": "kubok-vmk", "name": "Кубок ВМК", "location": "ВМК МГУ", "games_count": 0}
    ]

    # Пустой слот в счётчик не идёт -- только оценённая игра.
    client.post(f"/api/admin/tournaments/{tid}/games", json={"count": 1}, headers=headers)
    assert client.get("/api/tournaments").json()[0]["games_count"] == 0

    make_tournament_game(client, headers, tournament_id=tid, participants=_roster(ids))
    assert client.get("/api/tournaments").json()[0]["games_count"] == 1
