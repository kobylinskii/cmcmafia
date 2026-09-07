"""Регрессы на баги, найденные аудитом.

Каждый тест здесь once упал на живом коде -- это и есть причина, по которой он
существует. Держать их в одном файле, а не растаскивать по тематическим:
проверяемое правило в каждом случае уже описано в профильном тесте, а сюда
вынесена ровно та дорога, на которой правило обходилось.
"""

from __future__ import annotations

from tests.conftest import (
    BOT_HEADERS,
    make_players,
    make_session,
    make_tournament,
    make_tournament_game,
    register_bot_player,
    set_game_max_players,
)


def _roster(player_ids: list[int]) -> list[dict]:
    roles = ["don", "mafia", "mafia", "sheriff"] + ["citizen"] * 6
    return [
        {"player_id": pid, "seat_number": i + 1, "role": roles[i], "points_win": 0}
        for i, pid in enumerate(player_ids)
    ]


# --------------------------------------------------------------------- ППК
def test_result_alone_cannot_contradict_ppk(admin):
    """Смена ОДНОГО исхода не должна обходить правило ППК.

    Правило проверялось только когда в запросе есть participants, а форма
    оценки шлёт их всегда -- поэтому дыра и не всплывала. Но PUT с одним
    полем result валиден по схеме: игра с ППК дона переписывалась на победу
    мафии, и recompute_all начислял победу самому нарушителю.
    """
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    roster = _roster(ids)
    roster[0]["ppk"] = True  # ППК дона -> победа обязана уйти городу
    game = make_tournament_game(
        client, headers, tournament_id=tid, participants=roster, result="city_win"
    )

    resp = client.put(f"/api/admin/games/{game['id']}", json={"result": "mafia_win"}, headers=headers)
    assert resp.status_code == 422, resp.text
    assert "ППК" in resp.json()["detail"]

    # Исход в базе остался прежним, а не «наполовину применился».
    assert client.get(f"/api/games/{game['id']}").json()["result"] == "city_win"


def test_result_alone_still_works_without_ppk(admin):
    """Обычную игру исправить одним полем по-прежнему можно."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    game = make_tournament_game(
        client, headers, tournament_id=tid, participants=_roster(ids), result="city_win"
    )

    resp = client.put(f"/api/admin/games/{game['id']}", json={"result": "mafia_win"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"] == "mafia_win"


# ------------------------------------------------------------------ резерв
def test_leaving_the_table_for_staff_promotes_the_reserve(admin):
    """Уход игрока в штаб освобождает место -- очередь обязана сдвинуться.

    Промоушен жил только в отмене записи, и эта дорога его миновала: стол
    оставался неполным при непустом резерве.
    """
    client, headers = admin
    sid = make_session(client, headers, starts_at="2030-06-01T18:00:00Z")
    set_game_max_players(sid, 2)
    for tg in (9001, 9002, 9003):
        register_bot_player(client, tg, f"Бот{tg}")

    for tg in (9001, 9002):
        resp = client.post(
            f"/api/bot/sessions/{sid}/register?telegram_id={tg}",
            headers=BOT_HEADERS,
            json={"telegram_id": tg, "role_kind": "player"},
        )
        assert resp.json()["ok"], resp.text

    resp = client.post(
        f"/api/bot/sessions/{sid}/register?telegram_id=9003",
        headers=BOT_HEADERS,
        json={"telegram_id": 9003, "role_kind": "player"},
    )
    assert resp.json()["is_reserve"] is True, resp.text

    resp = client.post(
        f"/api/bot/sessions/{sid}/register?telegram_id=9001",
        headers=BOT_HEADERS,
        json={"telegram_id": 9001, "role_kind": "staff"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "host"
    # Боту нужно знать, кому написать -- те же поля, что и у отмены.
    assert body["promoted_telegram_id"] == 9003
    assert body["promoted_nickname"] == "Бот9003"

    roster = client.get(
        f"/api/bot/sessions/{sid}/roster?telegram_id=9001", headers=BOT_HEADERS
    ).json()
    assert [m["role"] for m in roster["registrations"]].count("player") == 2
    assert roster["reserves"] == []


def test_joining_staff_without_a_freed_seat_promotes_nobody(admin):
    """Тот, кто и не сидел за столом, ничьё место не освобождает."""
    client, headers = admin
    sid = make_session(client, headers, starts_at="2030-06-01T18:00:00Z")
    set_game_max_players(sid, 1)
    for tg in (9101, 9102, 9103):
        register_bot_player(client, tg, f"Бот{tg}")

    for tg, kind in ((9101, "player"), (9102, "player")):
        client.post(
            f"/api/bot/sessions/{sid}/register?telegram_id={tg}",
            headers=BOT_HEADERS,
            json={"telegram_id": tg, "role_kind": kind},
        )
    # 9102 ушёл в резерв (стол на одного). Третий идёт сразу в штаб.
    resp = client.post(
        f"/api/bot/sessions/{sid}/register?telegram_id=9103",
        headers=BOT_HEADERS,
        json={"telegram_id": 9103, "role_kind": "staff"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["promoted_telegram_id"] is None

    roster = client.get(
        f"/api/bot/sessions/{sid}/roster?telegram_id=9103", headers=BOT_HEADERS
    ).json()
    assert [r["nickname"] for r in roster["reserves"]] == ["Бот9102"]


# ------------------------------------------------------------------ logout
def test_logout_clears_cookies_without_a_live_access_token(admin):
    """Выйти можно и с протухшим access: иначе выход ломался ровно тогда,
    когда он нужен -- после 15 минут простоя."""
    client, headers = admin
    client.cookies.delete("access_token")

    resp = client.post("/api/auth/logout", headers=headers)
    assert resp.status_code == 200, resp.text
    # Именно refresh_token гейтит /mafia/admin в proxy.ts -- он обязан уйти.
    assert not client.cookies.get("refresh_token")
    assert not client.cookies.get("csrf_token")


def test_logout_still_refuses_a_cross_site_request(admin):
    """Выход не требует сессии, но требует CSRF-токен: иначе чужая страница
    могла бы разлогинивать админа по ссылке."""
    client, _ = admin
    assert client.post("/api/auth/logout").status_code == 403


# ------------------------------------------------- LIKE-шаблоны в текстовых полях
def test_like_wildcards_in_a_nickname_are_matched_literally(admin):
    """`%` и `_` в нике -- это символы ника, а не шаблон LIKE.

    Проверки занятости шли через голый ilike, и ник «%%» считался занятым
    первым же существующим игроком.
    """
    client, headers = admin
    make_players(client, headers, 1)  # «Игрок1»

    resp = client.post(
        "/api/admin/players", json={"nickname": "%%", "slug": "percent"}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    # `_` совпал бы с любым одиночным символом -- «И_рок1» не занят.
    resp = client.post(
        "/api/admin/players", json={"nickname": "И_рок1", "slug": "underscore"}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    # А настоящий дубль по-прежнему отклоняется, регистр при этом не важен.
    resp = client.post(
        "/api/admin/players", json={"nickname": "иГрОк1", "slug": "dupe"}, headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Ник уже занят"


def test_rating_search_treats_wildcards_literally(admin):
    """Поиск по рейтингу ищет введённое, а не раскрывает его в шаблон."""
    client, headers = admin
    ids = make_players(client, headers, 10)
    tid = make_tournament(client, headers)
    make_tournament_game(client, headers, tournament_id=tid, participants=_roster(ids))

    # Игроков в таблице десять, но ни одного с «%» в нике.
    assert client.get("/api/rating").json()["total"] == 10
    assert client.get("/api/rating", params={"q": "%"}).json()["total"] == 0
    # `_` тоже буквальный: под шаблон «Игрок_» попали бы все десять.
    assert client.get("/api/rating", params={"q": "Игрок_"}).json()["total"] == 0
    # Поиск остался поиском ПОДСТРОКИ: «Игрок1» -- это и «Игрок1», и «Игрок10».
    assert client.get("/api/rating", params={"q": "Игрок1"}).json()["total"] == 2
    assert client.get("/api/rating", params={"q": "Игрок7"}).json()["total"] == 1


def test_bot_registration_rejects_a_real_duplicate_nickname(admin):
    """Ник из бота проверяется тем же способом -- и настоящий дубль ловит."""
    client, headers = admin
    register_bot_player(client, 9201, "Пилот")

    resp = client.post(
        "/api/bot/players/register",
        headers=BOT_HEADERS,
        json={
            "telegram_id": 9202,
            "phone": "79001112233",
            "nickname": "пИлОт",
            "salutation": "т",
            "affiliation": "vmk",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Ник уже занят"


# ------------------------------------------------------- вход и деактивация
def test_deactivated_admin_cannot_log_in(admin_with_password):
    """Мягко удалённый игрок не должен проходить логин.

    Раньше вход удавался, кука выписывалась, proxy.ts пускал в админку -- и
    там всё отдавало 401 из get_current_site_user, который is_active как раз
    проверяет.
    """
    from app import models
    from app.database import SessionLocal

    client, _, password = admin_with_password
    db = SessionLocal()
    try:
        db.query(models.Player).filter(models.Player.site_username == "admin").one().is_active = False
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/auth/login", json={"username": "admin", "password": password})
    assert resp.status_code == 401
    # Текст тот же, что и при неверном пароле: наружу не должно быть видно,
    # существует ли такая учётка вообще.
    assert resp.json()["detail"] == "Неверный логин или пароль"
