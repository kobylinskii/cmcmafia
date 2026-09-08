"""Загрузка фото игрока: успешный путь и три сценария отказа.

Проверено вручную через реальную форму в браузере (реальный логин, реальный
<input type="file">, реальный fetch) -- все четыре сценария отработали
корректно. Здесь то же самое, но как воспроизводимый регресс-тест: успешная
загрузка меняет photo_url, слишком большой файл и не-изображение отдают 422 с
понятным текстом, а любое ДРУГОЕ исключение Pillow/диска (раньше улетало
наружу голым 500) тоже превращается в 422 -- см. player_service.save_player_photo.
"""

from __future__ import annotations

import io
import os

from PIL import Image

from app import models
from app.database import SessionLocal
from app.services import player_service
from tests.conftest import BOT_HEADERS, register_bot_player


def _jpeg_bytes(size=(300, 300), color=(180, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _upload(client, headers, player_id, raw_bytes, filename="avatar.jpg", content_type="image/jpeg"):
    return client.post(
        f"/api/admin/players/{player_id}/photo",
        headers=headers,
        files={"file": (filename, raw_bytes, content_type)},
    )


def test_valid_photo_is_saved_and_url_is_returned(admin):
    client, headers = admin
    player = client.post(
        "/api/admin/players", json={"nickname": "Аватарка", "slug": "avatarka"}, headers=headers
    ).json()

    resp = _upload(client, headers, player["id"], _jpeg_bytes())
    assert resp.status_code == 200, resp.text
    photo_url = resp.json()["photo_url"]
    assert photo_url.startswith("/media/players/") and photo_url.endswith(".jpg")

    updated = client.get(f"/api/admin/players/{player['id']}", headers=headers).json()
    assert updated["photo_url"] == photo_url


def test_same_file_can_be_uploaded_twice_in_a_row(admin):
    """Не проверяет фронтовый сброс <input>.value (это браузерное поведение,
    не тестируется через TestClient) -- проверяет, что СЕРВЕР как минимум не
    имеет собственных причин отказать на повторной идентичной загрузке."""
    client, headers = admin
    player = client.post(
        "/api/admin/players", json={"nickname": "Дубль", "slug": "dubl"}, headers=headers
    ).json()

    raw = _jpeg_bytes()
    first = _upload(client, headers, player["id"], raw)
    second = _upload(client, headers, player["id"], raw)
    assert first.status_code == 200 and second.status_code == 200
    # Второй файл физически новый (новое случайное имя), старый не переиспользуется.
    assert first.json()["photo_url"] != second.json()["photo_url"]


def test_oversized_file_is_rejected_with_a_clear_message(admin, monkeypatch):
    client, headers = admin
    player = client.post(
        "/api/admin/players", json={"nickname": "Толстяк", "slug": "tolstyak"}, headers=headers
    ).json()

    monkeypatch.setattr(player_service.settings, "max_photo_bytes", 100)
    resp = _upload(client, headers, player["id"], _jpeg_bytes())
    assert resp.status_code == 422, resp.text
    assert "большой" in resp.json()["detail"]


def test_non_image_file_is_rejected_with_a_clear_message(admin):
    client, headers = admin
    player = client.post(
        "/api/admin/players", json={"nickname": "Документ", "slug": "dokument"}, headers=headers
    ).json()

    resp = _upload(client, headers, player["id"], b"%PDF-1.4 not actually a pdf either", "doc.pdf", "application/pdf")
    assert resp.status_code == 422, resp.text
    assert "изображени" in resp.json()["detail"]


def test_unsupported_image_format_is_rejected(admin):
    """image/bmp декодируется Pillow без ошибок (значит проходит первую
    проверку), но не входит в ALLOWED_IMAGE_FORMATS -- отдельная ветка отказа."""
    client, headers = admin
    player = client.post(
        "/api/admin/players", json={"nickname": "Бумер", "slug": "bumer"}, headers=headers
    ).json()

    buf = io.BytesIO()
    Image.new("RGB", (50, 50)).save(buf, format="BMP")
    resp = _upload(client, headers, player["id"], buf.getvalue(), "avatar.bmp", "image/bmp")
    assert resp.status_code == 422, resp.text
    assert "Допустимые форматы" in resp.json()["detail"]


def test_unexpected_processing_failure_becomes_a_clean_422_not_a_500(admin, monkeypatch):
    """Раньше ловился только UnidentifiedImageError -- любое другое исключение
    Pillow или диска (здесь смоделировано через save()) улетало наружу как
    голый 500 без единого объяснения. save_player_photo обязана превратить
    его в понятный 422."""
    client, headers = admin
    player = client.post(
        "/api/admin/players", json={"nickname": "Сбой", "slug": "sboy"}, headers=headers
    ).json()

    raw = _jpeg_bytes()  # собрать ДО патча -- иначе сломается и подготовка теста

    def boom(self, *args, **kwargs):
        raise OSError("диск недоступен")

    monkeypatch.setattr(Image.Image, "save", boom)

    resp = _upload(client, headers, player["id"], raw)
    assert resp.status_code == 422, resp.text
    assert "Не удалось обработать" in resp.json()["detail"]


def _bot_upload(client, telegram_id, raw_bytes, filename="avatar.jpg", content_type="image/jpeg"):
    return client.post(
        "/api/bot/players/me/photo",
        headers=BOT_HEADERS,
        params={"telegram_id": telegram_id},
        files={"file": (filename, raw_bytes, content_type)},
    )


def test_bot_player_uploads_own_photo(admin):
    """Аватарка из Telegram. Модерации у неё нет (в отличие от текстовых полей
    профиля), поэтому photo_url меняется сразу и виден в /players/me."""
    client, _ = admin
    register_bot_player(client, 810001, "Фотогеничный")

    resp = _bot_upload(client, 810001, _jpeg_bytes())
    assert resp.status_code == 200, resp.text
    photo_url = resp.json()["photo_url"]
    assert photo_url.startswith("/media/players/") and photo_url.endswith(".jpg")

    profile = client.get(
        "/api/bot/players/me", headers=BOT_HEADERS, params={"telegram_id": 810001}
    ).json()
    assert profile["photo_url"] == photo_url


def test_bot_photo_upload_validates_the_file(admin):
    """Та же проверка, что и у админской ручки: сервис один на обе."""
    client, _ = admin
    register_bot_player(client, 810002, "Присылатель")

    resp = _bot_upload(client, 810002, b"not an image at all", "doc.pdf", "application/pdf")
    assert resp.status_code == 422, resp.text
    assert "изображени" in resp.json()["detail"]


def test_bot_photo_upload_requires_service_token(admin):
    client, _ = admin
    register_bot_player(client, 810003, "Безтокена")

    resp = client.post(
        "/api/bot/players/me/photo",
        params={"telegram_id": 810003},
        files={"file": ("avatar.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code in (401, 403)


def test_photo_upload_requires_site_admin_session(admin):
    client, headers = admin
    player = client.post(
        "/api/admin/players", json={"nickname": "Чужой", "slug": "chuzhoj"}, headers=headers
    ).json()

    client.cookies.clear()
    resp = _upload(client, headers, player["id"], _jpeg_bytes())
    assert resp.status_code == 401


# --------------------------------------------------------- модерация аватарки
# Фото подтверждённого игрока не встаёт в профиль сразу: оно ложится в ту же
# очередь, что и ФИО с ником (profile_change_service). Отдельная сложность,
# которой нет у текстовых полей: файл записан на диск ДО решения, и за
# непринятым надо убирать -- иначе волюм растёт на каждую отклонённую
# аватарку. Это здесь и проверяется, вплоть до наличия файла.
def _file_exists(photo_url: str) -> bool:
    return os.path.exists(
        os.path.join(player_service.settings.media_root, photo_url.removeprefix("/media/players/"))
    )


def _bot_profile(client, telegram_id: int) -> dict:
    return client.get(
        "/api/bot/players/me", headers=BOT_HEADERS, params={"telegram_id": telegram_id}
    ).json()


def _confirmed_bot_player(client, headers, telegram_id: int, nickname: str) -> int:
    register_bot_player(client, telegram_id, nickname)
    db = SessionLocal()
    try:
        player_id = (
            db.query(models.Player).filter(models.Player.telegram_id == telegram_id).one().id
        )
    finally:
        db.close()
    assert client.post(f"/api/admin/players/{player_id}/confirm", headers=headers).status_code == 200
    return player_id


def _pending_change(client, headers) -> dict:
    """Очередь админки отдаёт только pending -- решённое в неё не попадает."""
    queue = client.get("/api/admin/players/profile-changes", headers=headers).json()
    assert len(queue) == 1, queue
    return queue[0]


def test_photo_of_a_confirmed_player_waits_for_the_admin(admin):
    client, headers = admin
    _confirmed_bot_player(client, headers, 820001, "Ожидающий")

    resp = _bot_upload(client, 820001, _jpeg_bytes())
    assert resp.status_code == 200, resp.text
    assert resp.json()["pending"] is True
    new_url = resp.json()["photo_url"]

    profile = _bot_profile(client, 820001)
    assert profile["photo_url"] is None, "до решения админа фото в профиль не встаёт"
    assert profile["pending_changes"] == {"photo_url": new_url}
    # Файл уже на диске: показать админу картинку иначе нечем.
    assert _file_exists(new_url)

    change = _pending_change(client, headers)
    assert change["field"] == "photo_url"


def test_applied_photo_replaces_the_old_one_and_frees_its_file(admin):
    client, headers = admin
    player_id = _confirmed_bot_player(client, headers, 820002, "Сменщик")
    old_url = _upload(client, headers, player_id, _jpeg_bytes()).json()["photo_url"]

    new_url = _bot_upload(client, 820002, _jpeg_bytes(color=(30, 180, 30))).json()["photo_url"]
    change = _pending_change(client, headers)
    assert client.post(
        f"/api/admin/players/profile-changes/{change['id']}/apply", headers=headers
    ).status_code == 200

    assert _bot_profile(client, 820002)["photo_url"] == new_url
    assert _file_exists(new_url)
    assert not _file_exists(old_url), "прежний файл больше никому не нужен"


def test_rejected_photo_leaves_the_old_one_and_deletes_the_unaccepted_file(admin):
    client, headers = admin
    player_id = _confirmed_bot_player(client, headers, 820003, "Отказник")
    old_url = _upload(client, headers, player_id, _jpeg_bytes()).json()["photo_url"]

    new_url = _bot_upload(client, 820003, _jpeg_bytes(color=(30, 30, 180))).json()["photo_url"]
    change = _pending_change(client, headers)
    assert client.post(
        f"/api/admin/players/profile-changes/{change['id']}/reject",
        headers=headers,
        json={"reason": "На фото не вы"},
    ).status_code == 200

    assert _bot_profile(client, 820003)["photo_url"] == old_url
    assert _file_exists(old_url)
    assert not _file_exists(new_url), "непринятое фото не должно оставаться на диске"


def test_second_photo_supersedes_the_first_and_frees_its_file(admin):
    """Одно поле -- одна очередь: админу нужен последний вариант. Вытесненный
    файл при этом уже никому не принадлежит."""
    client, headers = admin
    _confirmed_bot_player(client, headers, 820004, "Переснимающий")

    first = _bot_upload(client, 820004, _jpeg_bytes()).json()["photo_url"]
    second = _bot_upload(client, 820004, _jpeg_bytes(color=(200, 200, 30))).json()["photo_url"]

    change = _pending_change(client, headers)
    assert change["new_value"] == second
    assert _file_exists(second)
    assert not _file_exists(first)


def test_unconfirmed_player_photo_applies_at_once(admin):
    """У непподтверждённого на проверке весь профиль целиком -- отдельная
    очередь по фото сделала бы отказ «пришлите другое фото» тупиком."""
    client, _ = admin
    register_bot_player(client, 820005, "Новичок")

    resp = _bot_upload(client, 820005, _jpeg_bytes())
    assert resp.json()["pending"] is False
    assert _bot_profile(client, 820005)["photo_url"] == resp.json()["photo_url"]
