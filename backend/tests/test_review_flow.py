"""Цикл «сессия запланирована -> её проведение подтвердили -> её оценивают»
(ARCHITECTURE.md, раздел 5).

Средний шаг раньше делала фоновая задача: любая прошедшая сессия сама
становилась 'played' и попадала в «Ждут оценки» -- вместе с играми, которые не
собрались и не состоялись. Теперь этот переход делает админ кнопкой во вкладке
«Игры → Расписание», и проверять надо ровно обратное: без подтверждения игра в
очередь оценки не попадает.

Планировщик переехал из бота в админку сайта, поэтому все ручки здесь --
`/api/admin/schedule/*` за сессией сайт-админа; бот-ручками остались только
запись игроков и профиль.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import (
    BOT_HEADERS,
    game_status,
    make_players,
    make_session,
    register_bot_player,
    set_game_max_players,
    set_game_time,
)


def _create_session(client, headers, *, max_players: int = 10, days_ahead: int = 1,
                    needs_rating: bool = True) -> int:
    session_id = make_session(
        client,
        headers,
        starts_at=(datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat(),
        location="Клуб",
        needs_rating=needs_rating,
    )
    if max_players != 10:
        set_game_max_players(session_id, max_players)
    return session_id


def _mark_played(client, headers, session_id: int):
    return client.post(f"/api/admin/schedule/sessions/{session_id}/played", headers=headers)


def _awaiting(client, headers) -> list[int]:
    resp = client.get("/api/admin/schedule/awaiting-confirmation", headers=headers)
    assert resp.status_code == 200, resp.text
    return [s["id"] for s in resp.json()]


def _day_cards(client, headers) -> list[dict]:
    resp = client.get("/api/admin/schedule/days", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _games_on(client, headers, day: str) -> list[int]:
    resp = client.get("/api/admin/schedule/sessions", headers=headers, params={"day": day})
    assert resp.status_code == 200, resp.text
    return [game["id"] for game in resp.json()]


def test_past_session_waits_for_the_admin_before_it_reaches_pending_review(admin):
    client, headers = admin
    session_id = _create_session(client, headers)

    # Пока игра в будущем -- ни оценивать, ни подтверждать нечего.
    assert client.get("/api/admin/games/pending-review", headers=headers).json() == []
    assert _awaiting(client, headers) == []

    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=3))

    # Время прошло -- игра ждёт ответа админа, но в очередь оценки не идёт:
    # именно этим она и отличается от игры, которая действительно состоялась.
    assert game_status(session_id) == "scheduled"
    assert _awaiting(client, headers) == [session_id]
    assert client.get("/api/admin/games/pending-review", headers=headers).json() == []

    assert _mark_played(client, headers, session_id).status_code == 200

    assert game_status(session_id) == "played"
    assert _awaiting(client, headers) == []
    pending = client.get("/api/admin/games/pending-review", headers=headers).json()
    assert [g["id"] for g in pending] == [session_id]


def test_future_game_cannot_be_marked_as_played(admin):
    client, headers = admin
    session_id = _create_session(client, headers, days_ahead=5)

    resp = _mark_played(client, headers, session_id)
    assert resp.status_code == 409, resp.text
    assert game_status(session_id) == "scheduled"


def test_confirming_the_same_game_twice_changes_nothing(admin):
    client, headers = admin
    session_id = _create_session(client, headers)
    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=1))

    assert _mark_played(client, headers, session_id).status_code == 200
    assert _mark_played(client, headers, session_id).status_code == 409
    assert game_status(session_id) == "played"


def test_game_that_did_not_happen_is_deleted_and_leaves_no_trace(admin):
    """«Не состоялась» -- это удаление: несыгранной игре нечего делать ни в
    очереди оценки, ни в списке ожидания."""
    client, headers = admin
    session_id = _create_session(client, headers)
    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=2))
    assert _awaiting(client, headers) == [session_id]

    resp = client.delete(f"/api/admin/schedule/sessions/{session_id}", headers=headers)
    assert resp.status_code == 200, resp.text

    assert _awaiting(client, headers) == []
    assert client.get("/api/admin/games/pending-review", headers=headers).json() == []


def test_game_without_rating_never_asks_to_be_confirmed(admin):
    """Игра, созданная с «оцениваться не будет», ничего от админа не ждёт.

    Она нужна только ради записи в боте: подтверждать её проведение незачем,
    в «Ждут оценки» она не идёт, а из расписания уходит сама, как только её
    время прошло. Записи при этом остаются -- по ним считается список на
    пропуск.
    """
    client, headers = admin
    session_id = _create_session(client, headers, needs_rating=False)
    day = _day_cards(client, headers)[0]["day"]
    assert _games_on(client, headers, day) == [session_id]

    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=2))

    assert _awaiting(client, headers) == []
    assert client.get("/api/admin/games/pending-review", headers=headers).json() == []
    # Из расписания исчезла и она, и её день -- нажимать там больше нечего.
    assert _games_on(client, headers, day) == []
    assert [card["day"] for card in _day_cards(client, headers)] == []
    # Но сама игра жива: её видно по прямой ссылке, и состав при ней.
    assert client.get(f"/api/admin/schedule/sessions/{session_id}", headers=headers).status_code == 200

    # Подтвердить проведение такой игры нельзя: оценивать её никто не будет.
    assert _mark_played(client, headers, session_id).status_code == 409


def test_rating_flag_can_be_flipped_until_the_game_is_rated(admin):
    """Флаг задаётся на день, но у отдельной игры его можно переключить.

    Снятие флага с уже подтверждённой игры возвращает её из «Ждут оценки»:
    иначе она осталась бы там навсегда -- оценивать её больше некому.
    """
    client, headers = admin
    session_id = _create_session(client, headers)
    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=2))
    _mark_played(client, headers, session_id)
    assert [g["id"] for g in client.get("/api/admin/games/pending-review", headers=headers).json()] == [session_id]

    resp = client.put(
        f"/api/admin/schedule/sessions/{session_id}", json={"needs_rating": False}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["needs_rating"] is False
    assert game_status(session_id) == "scheduled"
    assert client.get("/api/admin/games/pending-review", headers=headers).json() == []
    assert _awaiting(client, headers) == []


def test_rated_games_leave_the_schedule(admin):
    """Оценённая игра из расписания уходит: править состав и баллы можно только
    во вкладке оценённых игр, а список игровых дней иначе рос бы на каждый
    отыгранный день и не сокращался никогда."""
    client, headers = admin
    session_id = _create_session(client, headers)

    day = _day_cards(client, headers)[0]["day"]
    assert _games_on(client, headers, day) == [session_id]

    # Историческая игра, созданная сразу как rated, в расписании не появляется.
    player_ids = make_players(client, headers, 10)
    roles = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6
    rated = client.post(
        "/api/admin/games",
        json={
            "starts_at": "2026-02-01T18:00:00Z",
            "location": "Клуб",
            "game_type": "funky",
            "result": "city_win",
            "participants": [
                {"player_id": pid, "seat_number": seat, "role": role}
                for seat, (pid, role) in enumerate(zip(player_ids, roles), start=1)
            ],
        },
        headers=headers,
    )
    assert rated.status_code == 200, rated.text

    assert "01.02.2026" not in [card["day"] for card in _day_cards(client, headers)]
    assert _games_on(client, headers, "01.02.2026") == []
    # Неоценённая сессия на месте: с ней ещё есть что делать. Сверяем не по
    # номеру: игра за 01.02.2026 внесена задним числом и встала в нумерации
    # перед сессией, сдвинув её номер (game_service.resequence_game_ids).
    remaining = client.get(
        "/api/admin/schedule/sessions", headers=headers, params={"day": day}
    ).json()
    assert len(remaining) == 1
    assert remaining[0]["status"] == "scheduled"


def test_review_form_receives_the_roster_registered_in_the_bot(admin):
    """Форма оценки должна открываться с составом из registrations, а не пустой."""
    client, headers = admin
    session_id = _create_session(client, headers)

    for tg_id, nickname in [(201, "Первый"), (202, "Второй"), (203, "Третий")]:
        register_bot_player(client, tg_id, nickname)
        resp = client.post(
            f"/api/bot/sessions/{session_id}/register?telegram_id={tg_id}",
            headers=BOT_HEADERS,
            json={"telegram_id": tg_id, "role_kind": "player"},
        )
        assert resp.json()["ok"] is True, resp.text

    set_game_time(session_id, starts_at=datetime.now(timezone.utc) - timedelta(hours=2))
    _mark_played(client, headers, session_id)

    game = client.get(f"/api/admin/games/{session_id}", headers=headers).json()
    assert game["status"] == "played"
    assert game["participants"] == []  # мест за столом ещё нет -- их и вносит админ
    assert [r["nickname"] for r in game["roster"]] == ["Первый", "Второй", "Третий"]
    assert {r["role"] for r in game["roster"]} == {"player"}
    assert all(isinstance(r["player_id"], int) for r in game["roster"])


def test_schedule_card_shows_who_signed_up(admin):
    """Карточка слота в расписании отдаёт состав и резерв -- без них админ не
    видит, кого именно он переносит или удаляет вместе с игрой."""
    client, headers = admin
    session_id = _create_session(client, headers, max_players=1)

    for tg_id, nickname, kind in [(211, "Первый", "player"), (212, "Второй", "player"), (213, "Ведущий", "staff")]:
        register_bot_player(client, tg_id, nickname)
        resp = client.post(
            f"/api/bot/sessions/{session_id}/register?telegram_id={tg_id}",
            headers=BOT_HEADERS,
            json={"telegram_id": tg_id, "role_kind": kind},
        )
        assert resp.json()["ok"] is True, resp.text

    card = client.get(f"/api/admin/schedule/sessions/{session_id}", headers=headers).json()
    assert {r["nickname"] for r in card["roster"]["registrations"]} == {"Первый", "Ведущий"}
    assert [r["nickname"] for r in card["roster"]["reserves"]] == ["Второй"]
    assert card["players"] == 1 and card["hosts"] == 1 and card["reserves"] == 1


def test_staff_comes_first_in_the_roster(admin):
    """Ведущий и судья идут перед игроками -- админу так удобнее читать состав."""
    client, headers = admin
    session_id = _create_session(client, headers)

    register_bot_player(client, 301, "Игрок")
    register_bot_player(client, 302, "Ведущий")
    for tg_id, kind in [(301, "player"), (302, "staff")]:
        resp = client.post(
            f"/api/bot/sessions/{session_id}/register?telegram_id={tg_id}",
            headers=BOT_HEADERS,
            json={"telegram_id": tg_id, "role_kind": kind},
        )
        assert resp.json()["ok"] is True, resp.text

    game = client.get(f"/api/admin/games/{session_id}", headers=headers).json()
    assert [(r["nickname"], r["role"]) for r in game["roster"]] == [
        ("Ведущий", "host"),
        ("Игрок", "player"),
    ]


def test_public_game_response_carries_no_roster(admin):
    """roster -- служебное поле админки; публичному API он не нужен."""
    client, headers = admin
    session_id = _create_session(client, headers)
    register_bot_player(client, 401, "Кто-то")
    client.post(
        f"/api/bot/sessions/{session_id}/register?telegram_id=401",
        headers=BOT_HEADERS,
        json={"telegram_id": 401, "role_kind": "player"},
    )

    # Публичный эндпоинт отдаёт только оценённые игры, эта ещё не оценена.
    assert client.get(f"/api/games/{session_id}").status_code == 404


def test_registration_closes_at_registration_until(admin):
    """registration_until -- дедлайн записи, а не украшение: до правки
    is_session_open смотрел только на starts_at, и закрыть запись заранее
    было невозможно."""
    client, headers = admin
    session_id = _create_session(client, headers, days_ahead=3)
    register_bot_player(client, 501, "Опоздавший")

    now = datetime.now(timezone.utc)
    set_game_time(session_id, registration_until=now - timedelta(minutes=1))

    resp = client.post(
        f"/api/bot/sessions/{session_id}/register?telegram_id=501",
        headers=BOT_HEADERS,
        json={"telegram_id": 501, "role_kind": "player"},
    )
    assert resp.status_code == 404, "запись после дедлайна должна быть закрыта"

    session = client.get(
        f"/api/bot/sessions/{session_id}?telegram_id=501", headers=BOT_HEADERS
    ).json()
    assert session["is_open"] is False

    # Сдвинули дедлайн вперёд -- запись снова открыта.
    set_game_time(session_id, registration_until=now + timedelta(days=2))
    resp = client.post(
        f"/api/bot/sessions/{session_id}/register?telegram_id=501",
        headers=BOT_HEADERS,
        json={"telegram_id": 501, "role_kind": "player"},
    )
    assert resp.status_code == 200 and resp.json()["ok"] is True, resp.text


def test_moving_a_game_carries_the_registration_deadline_with_it(admin):
    """Перенос игры двигает и дедлайн записи.

    Планировщик ставит их равными при создании; отставший дедлайн закрыл бы
    запись на игру, которую только что перенесли на неделю вперёд.
    """
    client, headers = admin
    session_id = _create_session(client, headers, days_ahead=1)
    later = (datetime.now(timezone.utc) + timedelta(days=8)).replace(microsecond=0)

    resp = client.put(
        f"/api/admin/schedule/sessions/{session_id}",
        json={"starts_at": later.isoformat()},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert datetime.fromisoformat(resp.json()["registration_until"]) == later
    assert resp.json()["is_open"] is True


def test_planner_refuses_to_double_book_a_time(admin):
    """Пересечение по времени -- почти всегда повторное создание уже
    заведённого дня, а не намерение посадить два стола разом."""
    client, headers = admin
    first = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    body = {
        "starts_at": first.isoformat(),
        "count": 3,
        "step_minutes": 60,
        "location": "Клуб",
        "game_type": "funky",
    }
    assert client.post("/api/admin/schedule/plan", json=body, headers=headers).status_code == 200

    preview = client.post("/api/admin/schedule/plan/preview", json=body, headers=headers)
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["starts_at_list"]) == 3
    assert len(preview.json()["conflicts"]) == 3

    assert client.post("/api/admin/schedule/plan", json=body, headers=headers).status_code == 409


def test_day_grouping_uses_moscow_midnight_not_utc(admin):
    """Игра в 00:30 МСК -- это 21:30 UTC предыдущих суток. Группировка по дням
    обязана считать по московскому времени, иначе игра уезжает в соседний день.
    Раньше и группировка, и отбор делались на Python над всей таблицей игр;
    теперь это SQL, и границы суток должны остаться теми же."""
    client, headers = admin

    # Порядок создания -- хронологический, иначе вторая игра встала бы в
    # нумерации перед первой и сдвинула её номер: id игры -- это её место в
    # хронологии (game_service.resequence_game_ids). К самой группировке по
    # дням это отношения не имеет.
    # 2026-12-02T15:00Z == 02.12.2026 18:00 МСК
    evening_id = make_session(client, headers, starts_at="2026-12-02T15:00:00Z", location="Клуб")
    # 2026-12-02T21:30Z == 03.12.2026 00:30 МСК
    late_id = make_session(client, headers, starts_at="2026-12-02T21:30:00Z", location="Клуб")

    assert _games_on(client, headers, "02.12.2026") == [evening_id]
    assert _games_on(client, headers, "03.12.2026") == [late_id]
    assert [d["day"] for d in _day_cards(client, headers)] == ["02.12.2026", "03.12.2026"]
