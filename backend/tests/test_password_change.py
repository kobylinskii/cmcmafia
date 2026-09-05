"""Смена собственного пароля.

Раньше сменить пароль можно было только двумя способами: перевыдать случайный
временный (кнопка «ключ» в разделе «Игроки») или запустить CLI-скрипт на
сервере. Задать себе постоянный пароль из интерфейса было нельзя.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

NEW_PASSWORD = "sovsem-drugoj-parol-2026"


def _login(password: str):
    """Каждый раз чистый клиент: свои куки, чужая сессия не мешает."""
    return TestClient(app).post("/api/auth/login", json={"username": "admin", "password": password})


def test_password_change_replaces_the_old_one(admin_with_password):
    client, headers, old_password = admin_with_password

    resp = client.post(
        "/api/auth/password",
        json={"current_password": old_password, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # Вкладка не разлогинивается: эндпоинт выдаёт свежую пару токенов.
    assert client.get("/api/auth/me").status_code == 200

    assert _login(NEW_PASSWORD).status_code == 200
    assert _login(old_password).status_code == 401


def test_wrong_current_password_is_rejected(admin_with_password):
    client, headers, old_password = admin_with_password
    resp = client.post(
        "/api/auth/password",
        json={"current_password": "не тот пароль", "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert resp.status_code == 400
    assert _login(old_password).status_code == 200


def test_new_password_must_be_long_enough(admin_with_password):
    client, headers, old_password = admin_with_password
    resp = client.post(
        "/api/auth/password",
        json={"current_password": old_password, "new_password": "korotkij"},
        headers=headers,
    )
    assert resp.status_code == 422


def test_new_password_must_differ_from_current(admin_with_password):
    client, headers, old_password = admin_with_password
    resp = client.post(
        "/api/auth/password",
        json={"current_password": old_password, "new_password": old_password},
        headers=headers,
    )
    assert resp.status_code == 422


def test_password_change_requires_csrf_header(admin_with_password):
    client, _, old_password = admin_with_password
    resp = client.post(
        "/api/auth/password",
        json={"current_password": old_password, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 403


def test_password_change_requires_a_session(admin_with_password):
    client, headers, old_password = admin_with_password
    client.cookies.clear()
    resp = client.post(
        "/api/auth/password",
        json={"current_password": old_password, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert resp.status_code == 401


def test_guessing_the_current_password_hits_the_login_lockout(admin_with_password):
    """Иначе эндпоинт стал бы способом перебирать пароль в обход блокировки
    на /login: сессия живёт неделю, попыток было бы сколько угодно."""
    client, headers, old_password = admin_with_password

    for _ in range(5):
        resp = client.post(
            "/api/auth/password",
            json={"current_password": "мимо", "new_password": NEW_PASSWORD},
            headers=headers,
        )
        assert resp.status_code == 400

    assert _login(old_password).status_code == 423


def test_session_cookies_are_lax_so_external_links_keep_the_session(admin_with_password):
    """SameSite=Strict не отдавал куку ни при одном переходе извне: по кнопке
    «Оценить игру» из бота или по ссылке из другой вкладки админ попадал на
    логин, хотя сессия жива. От CSRF защищает double-submit токен, не этот флаг.
    """
    client, _, password = admin_with_password
    resp = TestClient(app).post(
        "/api/auth/login", json={"username": "admin", "password": password}
    )
    assert resp.status_code == 200, resp.text

    # get_list, а не items(): httpx склеивает одноимённые заголовки в одну
    # строку через запятую, и три Set-Cookie превращаются в одну.
    cookies = resp.headers.get_list("set-cookie")
    assert len(cookies) == 3, cookies
    for raw in cookies:
        assert "samesite=lax" in raw.lower(), raw
    # httpOnly остаётся у токенов и снимается только с CSRF-куки: её обязан
    # прочитать JS, чтобы положить в заголовок.
    assert sum("httponly" in raw.lower() for raw in cookies) == 2
