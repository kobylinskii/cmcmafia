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

from PIL import Image

from app import models
from app.services import player_service


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


def test_photo_upload_requires_site_admin_session(admin):
    client, headers = admin
    player = client.post(
        "/api/admin/players", json={"nickname": "Чужой", "slug": "chuzhoj"}, headers=headers
    ).json()

    client.cookies.clear()
    resp = _upload(client, headers, player["id"], _jpeg_bytes())
    assert resp.status_code == 401
