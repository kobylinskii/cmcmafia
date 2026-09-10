"""Выдача и отзыв прав: вход на сайт и админка бота.

Самая чувствительная часть API -- она и раздаёт доступ. Тесты до сих пор
ходили в сервисный слой напрямую (conftest.admin заводит первого админа
именно так), а сами HTTP-ручки не проверялись ни разу.
"""

from __future__ import annotations

from tests.conftest import BOT_HEADERS, make_bot_admin, register_bot_player


def test_granted_site_access_actually_lets_the_player_in(admin):
    """Выданный логин -- рабочий: временным паролем можно войти, и вошедший
    получает права админа сайта."""
    client, headers = admin
    player = client.post(
        "/api/admin/players", json={"nickname": "Норд", "slug": "nord"}, headers=headers
    ).json()

    resp = client.post(
        f"/api/admin/players/{player['id']}/site-access",
        params={"username": "nord"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    granted = resp.json()
    assert granted["site_username"] == "nord"
    assert granted["temp_password"]

    # Логин заводится сразу рабочим -- отдельным клиентом, чтобы не сбить
    # куки действующего админа.
    from fastapi.testclient import TestClient

    from app.main import app

    fresh = TestClient(app)
    login = fresh.post(
        "/api/auth/login", json={"username": "nord", "password": granted["temp_password"]}
    )
    assert login.status_code == 200, login.text
    assert login.json()["is_site_admin"] is True
    assert fresh.get("/api/auth/me").json()["nickname"] == "Норд"


def test_site_access_username_cannot_be_stolen_from_another_player(admin):
    client, headers = admin
    first = client.post(
        "/api/admin/players", json={"nickname": "Оникс", "slug": "onyx"}, headers=headers
    ).json()
    second = client.post(
        "/api/admin/players", json={"nickname": "Гроза", "slug": "groza"}, headers=headers
    ).json()

    assert client.post(
        f"/api/admin/players/{first['id']}/site-access", params={"username": "shared"}, headers=headers
    ).status_code == 200
    resp = client.post(
        f"/api/admin/players/{second['id']}/site-access", params={"username": "shared"}, headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Такой логин уже занят"

    # Перевыдача тому же игроку -- это смена пароля, а не конфликт.
    assert client.post(
        f"/api/admin/players/{first['id']}/site-access", params={"username": "shared"}, headers=headers
    ).status_code == 200

    assert client.post(
        "/api/admin/players/9999/site-access", params={"username": "ghost"}, headers=headers
    ).status_code == 404


def test_revoking_site_access_closes_the_door(admin):
    """После отзыва прежний пароль перестаёт работать, а флаг админа снят."""
    client, headers = admin
    player = client.post(
        "/api/admin/players", json={"nickname": "Ратник", "slug": "ratnik"}, headers=headers
    ).json()
    password = client.post(
        f"/api/admin/players/{player['id']}/site-access",
        params={"username": "ratnik"},
        headers=headers,
    ).json()["temp_password"]

    resp = client.delete(f"/api/admin/players/{player['id']}/site-access", headers=headers)
    assert resp.status_code == 200, resp.text

    card = client.get(f"/api/admin/players/{player['id']}", headers=headers).json()
    assert card["site_username"] is None
    assert card["is_site_admin"] is False

    from fastapi.testclient import TestClient

    from app.main import app

    fresh = TestClient(app)
    assert fresh.post(
        "/api/auth/login", json={"username": "ratnik", "password": password}
    ).status_code == 401

    assert client.delete("/api/admin/players/9999/site-access", headers=headers).status_code == 404


def test_bot_admin_rights_are_granted_and_revoked_from_the_site(admin):
    """Права бот-админа снимаются с сайта: у клуба должен оставаться способ
    разжаловать админа, не заходя в бота."""
    client, headers = admin
    register_bot_player(client, 7001, "Виконт")

    resp = client.post("/api/admin/bot-admins", params={"telegram_id": 7001}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "granted"
    player_id = resp.json()["player_id"]

    listed = client.get("/api/admin/bot-admins", headers=headers).json()
    assert [p["nickname"] for p in listed] == ["Виконт"]

    # Повторная выдача -- не ошибка, а «уже админ».
    assert client.post(
        "/api/admin/bot-admins", params={"telegram_id": 7001}, headers=headers
    ).json()["status"] == "already_admin"

    resp = client.delete(f"/api/admin/bot-admins/{player_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert client.get("/api/admin/bot-admins", headers=headers).json() == []
    # Разжалованный больше не проходит в админку бота.
    assert client.get(
        "/api/bot/admin/admins", params={"telegram_id": 7001}, headers=BOT_HEADERS
    ).status_code == 403

    assert client.delete("/api/admin/bot-admins/9999", headers=headers).status_code == 404


def test_pending_bot_admin_invitation_can_be_withdrawn(admin):
    """Приглашение по @username до регистрации человека можно отозвать.

    Иначе выданное по ошибке приглашение сработало бы молча -- в момент, когда
    приглашённый когда-нибудь нажмёт /start.
    """
    client, headers = admin
    admin_tg = 7100
    make_bot_admin(admin_tg, nickname="Штаб", slug="shtab")

    resp = client.post(
        "/api/bot/admin/admins",
        params={"telegram_id": admin_tg},
        headers=BOT_HEADERS,
        json={"username": "@Novichok"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "pending", "username": "novichok"}
    assert client.get(
        "/api/bot/admin/admins/pending", params={"telegram_id": admin_tg}, headers=BOT_HEADERS
    ).json() == ["novichok"]

    # Отзыв -- по тому же имени, регистр и «@» роли не играют.
    resp = client.delete(
        "/api/bot/admin/admins/pending/@NOVICHOK",
        params={"telegram_id": admin_tg},
        headers=BOT_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"removed": True}
    assert client.get(
        "/api/bot/admin/admins/pending", params={"telegram_id": admin_tg}, headers=BOT_HEADERS
    ).json() == []

    # Отозванное приглашение при регистрации уже не срабатывает.
    profile = client.post(
        "/api/bot/players/register",
        headers=BOT_HEADERS,
        json={
            "telegram_id": 7101,
            "telegram_username": "novichok",
            "phone": "79005550101",
            "nickname": "Новичок",
            "salutation": "т",
            "affiliation": "vmk",
        },
    ).json()
    assert profile["is_bot_admin"] is False

    # Повторный отзыв ничего не находит и не падает.
    assert client.delete(
        "/api/bot/admin/admins/pending/novichok",
        params={"telegram_id": admin_tg},
        headers=BOT_HEADERS,
    ).json() == {"removed": False}


def _login_as(username: str, password: str) -> tuple:
    """Отдельный клиент под другим админом: общий TestClient держит куки, и
    вход вторым сбил бы сессию первого прямо посреди теста."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return client, {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _grant(client, headers, nickname: str, slug: str) -> tuple[int, str]:
    player_id = client.post(
        "/api/admin/players", json={"nickname": nickname, "slug": slug}, headers=headers
    ).json()["id"]
    resp = client.post(
        f"/api/admin/players/{player_id}/site-access", params={"username": slug}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return player_id, resp.json()["temp_password"]


def test_site_admin_rights_are_revoked_down_the_chain_only(admin):
    """Кто выдал права, тот их и снимает -- вместе со всем, что выросло ниже.

    Админ1 (корневой, из фикстуры) назначил админа2, тот -- админа3. Значит
    админ1 разжалует обоих, админ2 -- только третьего, админ3 -- никого.
    """
    client1, headers1 = admin
    id2, password2 = _grant(client1, headers1, "Второй", "second")
    client2, headers2 = _login_as("second", password2)
    id3, password3 = _grant(client2, headers2, "Третий", "third")
    client3, headers3 = _login_as("third", password3)

    me3 = client3.get("/api/auth/me").json()
    assert me3["player_id"] == id3

    # Снизу вверх -- нельзя: ни разжаловать, ни удалить, ни перевыдать пароль
    # (перевыдача -- это захват учётки, то есть тот же отзыв).
    for target in (id2, client1.get("/api/auth/me").json()["player_id"]):
        assert client3.delete(f"/api/admin/players/{target}/site-access", headers=headers3).status_code == 422
        assert client3.delete(f"/api/admin/players/{target}", headers=headers3).status_code == 422
        assert client3.post(
            f"/api/admin/players/{target}/site-access", params={"username": "hijack"}, headers=headers3
        ).status_code == 422

    # Сверху вниз -- можно.
    assert client2.delete(f"/api/admin/players/{id3}/site-access", headers=headers2).status_code == 200
    assert client1.get(f"/api/admin/players/{id3}", headers=headers1).json()["is_site_admin"] is False

    assert client1.delete(f"/api/admin/players/{id2}/site-access", headers=headers1).status_code == 200
    assert client1.get(f"/api/admin/players/{id2}", headers=headers1).json()["is_site_admin"] is False


def test_revoked_admins_grantees_move_up_to_his_own_grantor(admin):
    """Разжаловали середину цепочки -- назначенные ею переходят выше, а не
    становятся неприкосновенными корнями."""
    client1, headers1 = admin
    id2, password2 = _grant(client1, headers1, "Второй", "second")
    client2, headers2 = _login_as("second", password2)
    id3, _ = _grant(client2, headers2, "Третий", "third")

    assert client1.delete(f"/api/admin/players/{id2}/site-access", headers=headers1).status_code == 200

    me1 = client1.get("/api/auth/me").json()["player_id"]
    assert client1.get(f"/api/admin/players/{id3}", headers=headers1).json()["site_admin_granted_by_id"] == me1
    assert client1.delete(f"/api/admin/players/{id3}/site-access", headers=headers1).status_code == 200


def test_admin_can_always_step_down_himself(admin):
    """Себя разжаловать можно и снизу цепочки -- иначе выйти из админки нечем."""
    client1, headers1 = admin
    id2, password2 = _grant(client1, headers1, "Второй", "second")
    client2, headers2 = _login_as("second", password2)

    assert client2.delete(f"/api/admin/players/{id2}/site-access", headers=headers2).status_code == 200
    assert client1.get(f"/api/admin/players/{id2}", headers=headers1).json()["is_site_admin"] is False
