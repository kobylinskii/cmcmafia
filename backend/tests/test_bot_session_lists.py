"""Что игрок видит в боте: список дней, список слотов и своя карточка.

Это главный экран бота -- три ручки, через которые проходит каждый, кто
открывает «Игры». Отбор в registration_service.list_open_sessions устроен
неочевидно (турнирные слоты вон, свои записи вон, дни считаются по московской
полуночи), а проверялся до сих пор только косвенно, через запись на игру.
"""

from __future__ import annotations

from tests.conftest import (
    BOT_HEADERS,
    make_players,
    make_session,
    make_sessions,
    make_tournament,
    make_tournament_game,
    register_bot_player,
    set_game_time,
)


def _open_sessions(client, tg_id: int, **params) -> list[dict]:
    resp = client.get(
        "/api/bot/sessions/open", params={"telegram_id": tg_id, **params}, headers=BOT_HEADERS
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _game_days(client, tg_id: int, **params) -> list[str]:
    resp = client.get(
        "/api/bot/game-days", params={"telegram_id": tg_id, **params}, headers=BOT_HEADERS
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_open_sessions_lists_upcoming_slots_with_their_occupancy(admin):
    client, headers = admin
    make_sessions(client, headers, starts_at="2030-06-01T15:00:00Z", count=2, step_minutes=60)
    register_bot_player(client, 8001, "Зодиак")
    register_bot_player(client, 8002, "Индиго")

    sessions = _open_sessions(client, 8001)
    assert len(sessions) == 2
    first = sessions[0]
    assert first["is_open"] is True
    assert (first["hosts"], first["judges"], first["players"], first["reserves"]) == (0, 0, 0, 0)
    assert first["max_players"] == 10
    # Порядок -- по времени начала, а не по номеру.
    assert sessions[0]["starts_at"] < sessions[1]["starts_at"]

    # Счётчики живые: чужая запись видна всем.
    client.post(
        f"/api/bot/sessions/{first['id']}/register?telegram_id=8002",
        headers=BOT_HEADERS,
        json={"telegram_id": 8002, "role_kind": "staff"},
    )
    assert _open_sessions(client, 8001)[0]["hosts"] == 1


def test_open_sessions_hide_the_players_own_registrations(admin):
    """Записанный не видит игру в списке записи -- она уехала в «Мои игры»."""
    client, headers = admin
    ids = make_sessions(client, headers, starts_at="2030-06-01T15:00:00Z", count=2)
    register_bot_player(client, 8101, "Люмен")

    taken = ids[0]["id"]
    client.post(
        f"/api/bot/sessions/{taken}/register?telegram_id=8101",
        headers=BOT_HEADERS,
        json={"telegram_id": 8101, "role_kind": "player"},
    )
    assert [s["id"] for s in _open_sessions(client, 8101)] == [ids[1]["id"]]

    # Резерв прячет игру так же: второй раз предлагать её незачем.
    client.post(
        f"/api/bot/sessions/{ids[1]['id']}/reserve?telegram_id=8101",
        headers=BOT_HEADERS,
        json={"telegram_id": 8101},
    )
    assert _open_sessions(client, 8101) == []
    # А другому игроку обе по-прежнему видны.
    register_bot_player(client, 8102, "Ёрш")
    assert len(_open_sessions(client, 8102)) == 2


def test_open_sessions_exclude_past_games_and_tournament_slots(admin):
    """Прошедшая игра и турнирный слот в записи не показываются.

    Турнирный слот лежит в том же статусе 'scheduled' с плейсхолдер-датой
    турнира: без явного отсева игрок записался бы на игру, которая на деле
    ждёт оценки этапа.
    """
    client, headers = admin
    register_bot_player(client, 8201, "Мираж")

    # Турнирный слот заводим ПЕРВЫМ: его плейсхолдер-дата -- начало турнира,
    # то есть раньше сессий, и добавление после них перенумеровало бы игры
    # (game_service.resequence_game_ids), обесценив сохранённые id.
    tid = make_tournament(client, headers)
    client.post(f"/api/admin/tournaments/{tid}/games", json={"count": 1}, headers=headers)

    upcoming = make_session(client, headers, starts_at="2030-06-01T15:00:00Z")
    stale = make_session(client, headers, starts_at="2030-06-02T15:00:00Z")

    # Турнирного слота в записи нет, хотя он тоже 'scheduled'.
    assert sorted(s["id"] for s in _open_sessions(client, 8201)) == sorted([upcoming, stale])
    assert all(s["game_type"] != "tournament" for s in _open_sessions(client, 8201))

    # Двигаем одну игру в прошлое -- она уходит из записи.
    from datetime import datetime, timezone

    set_game_time(stale, starts_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert [s["id"] for s in _open_sessions(client, 8201)] == [upcoming]


def test_open_sessions_filter_by_type_and_day(admin):
    client, headers = admin
    register_bot_player(client, 8301, "Кобра")
    funky = make_session(client, headers, starts_at="2030-06-01T15:00:00Z", game_type="funky")
    training = make_session(client, headers, starts_at="2030-06-02T15:00:00Z", game_type="training")

    assert [s["id"] for s in _open_sessions(client, 8301, game_type="funky")] == [funky]
    assert [s["id"] for s in _open_sessions(client, 8301, game_type="training")] == [training]
    # 'all' -- это «без фильтра», а не тип игры.
    assert len(_open_sessions(client, 8301, game_type="all")) == 2

    assert [s["id"] for s in _open_sessions(client, 8301, day="01.06.2030")] == [funky]
    assert _open_sessions(client, 8301, day="09.09.2030") == []


def test_game_days_are_grouped_by_moscow_midnight(admin):
    """День игры -- московский, а не UTC: игра в 00:30 МСК идёт 21:30 UTC
    предыдущих суток и обязана попасть в следующий день."""
    client, headers = admin
    register_bot_player(client, 8401, "Дельта")
    make_session(client, headers, starts_at="2030-06-01T21:30:00Z")  # 02.06 00:30 МСК
    make_session(client, headers, starts_at="2030-06-02T15:00:00Z")  # 02.06 18:00 МСК
    make_session(client, headers, starts_at="2030-06-03T15:00:00Z")

    assert _game_days(client, 8401) == ["02.06.2030", "03.06.2030"]

    # Список дней согласован со списком слотов: обе ручки берут один отбор.
    assert len(_open_sessions(client, 8401, day="02.06.2030")) == 2


def test_game_days_shrink_as_the_player_signs_up(admin):
    client, headers = admin
    register_bot_player(client, 8501, "Жетон")
    only_game = make_session(client, headers, starts_at="2030-06-01T15:00:00Z")
    assert _game_days(client, 8501) == ["01.06.2030"]

    client.post(
        f"/api/bot/sessions/{only_game}/register?telegram_id=8501",
        headers=BOT_HEADERS,
        json={"telegram_id": 8501, "role_kind": "player"},
    )
    assert _game_days(client, 8501) == []


def test_my_stats_card_matches_the_public_profile(admin):
    """Карточка профиля в боте показывает те же числа, что и сайт."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    roles = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6
    make_tournament_game(
        client,
        headers,
        tournament_id=tid,
        participants=[
            {"player_id": pid, "seat_number": i + 1, "role": roles[i], "points_win": 0}
            for i, pid in enumerate(ids)
        ],
        result="mafia_win",
    )

    # Привязываем telegram к первому игроку (дон, то есть победитель).
    from app import models
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        db.get(models.Player, ids[0]).telegram_id = 8601
        db.commit()
    finally:
        db.close()

    resp = client.get(
        "/api/bot/players/me/stats", params={"telegram_id": 8601}, headers=BOT_HEADERS
    )
    assert resp.status_code == 200, resp.text
    bot_stats = resp.json()
    assert bot_stats["total_games"] == 1
    assert bot_stats["wins"] == 1
    assert bot_stats["win_rate"] == 1.0
    assert bot_stats["rating_games_count"] == 1
    assert bot_stats["rank"] is not None

    site_stats = client.get("/api/players/player1").json()["stats"]
    for field in ("total_games", "wins", "win_rate", "rating", "rating_games_count", "rank"):
        assert bot_stats[field] == site_stats[field], field


def test_my_stats_are_visible_to_an_unconfirmed_player(admin):
    """Модерация прячет игрока с САЙТА, а не от него самого.

    Неподтверждённого нет ни в рейтинге, ни на публичных страницах -- но своя
    карточка в боте у него открывается, иначе бот выглядел бы сломанным.
    """
    client, _ = admin
    register_bot_player(client, 8701, "Аврора")

    resp = client.get(
        "/api/bot/players/me/stats", params={"telegram_id": 8701}, headers=BOT_HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "total_games": 0,
        "wins": 0,
        "win_rate": None,
        "rating": None,
        "rating_games_count": 0,
        "rank": None,
    }
    # А на сайте его при этом нет.
    assert client.get("/api/players/avrora").status_code == 404


def test_bot_session_lists_require_the_service_token(admin):
    client, headers = admin
    register_bot_player(client, 8801, "Барс")
    for url in ("/api/bot/sessions/open", "/api/bot/game-days", "/api/bot/players/me/stats"):
        assert client.get(url, params={"telegram_id": 8801}).status_code == 401
        assert client.get(
            url, params={"telegram_id": 8801}, headers={"Authorization": "Bearer wrong"}
        ).status_code == 401
    # Неизвестный telegram_id -- 404, а не пустой список.
    assert client.get(
        "/api/bot/sessions/open", params={"telegram_id": 999999}, headers=BOT_HEADERS
    ).status_code == 404
