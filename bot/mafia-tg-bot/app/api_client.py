"""Тонкий HTTP-клиент к общему backend API (см. ARCHITECTURE.md v3).

Бот больше не подключается к Postgres напрямую — вся запись и чтение идёт
через FastAPI-бэкенд, тот же самый, что обслуживает сайт. Авторизация —
сервисный токен BOT_SERVICE_TOKEN в заголовке Authorization, действующий
пользователь передаётся явно как telegram_id (см. ARCHITECTURE.md, раздел 9.1
про модель доверия бот-API).

Даты бот исторически хранит и показывает как наивные строки "ДД.ММ.ГГГГ ЧЧ:ММ"
в московском времени. API работает с timezone-aware datetime (UTC). Конвертация
между этими представлениями — целиком ответственность этого модуля, остальной
код бота продолжает работать со строками "ДД.ММ.ГГГГ ЧЧ:ММ", как и раньше.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

LOCAL_TZ = ZoneInfo("Europe/Moscow")


class ApiError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class NotFoundError(ApiError):
    pass


class ConflictError(ApiError):
    pass


def _extract_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            loc = ".".join(str(p) for p in item.get("loc", []) if p != "body")
            parts.append(f"{loc}: {item.get('msg')}" if loc else str(item.get("msg")))
        return "; ".join(parts) or "Ошибка валидации"
    return str(body)


def to_api_datetime(day_time: str) -> str:
    """'ДД.ММ.ГГГГ ЧЧ:ММ' (московское время) -> ISO-строка с таймзоной для API."""
    naive = datetime.strptime(day_time, "%d.%m.%Y %H:%M")
    aware = naive.replace(tzinfo=LOCAL_TZ)
    return aware.isoformat()


def from_api_datetime(value: str) -> datetime:
    """ISO-строка от API -> datetime в московском времени (для форматирования)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(LOCAL_TZ)


def format_day_time(value: str) -> str:
    return from_api_datetime(value).strftime("%d.%m.%Y %H:%M")


def format_time(value: str) -> str:
    return from_api_datetime(value).strftime("%H:%M")


def format_day(value: str) -> str:
    return from_api_datetime(value).strftime("%d.%m.%Y")


class ApiClient:
    def __init__(self, base_url: str, service_token: str, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {service_token}"},
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._client.request(method, path, **kwargs)
        if response.status_code == 404:
            raise NotFoundError(404, _extract_message(response))
        if response.status_code == 409:
            raise ConflictError(409, _extract_message(response))
        if response.status_code >= 400:
            raise ApiError(response.status_code, _extract_message(response))
        return response

    # ------------------------------------------------------------- players
    async def get_profile(self, tg_id: int, telegram_username: str | None = None) -> dict | None:
        params = {"telegram_id": tg_id}
        if telegram_username:
            params["telegram_username"] = telegram_username
        try:
            resp = await self._request("GET", "/api/bot/players/me", params=params)
        except NotFoundError:
            return None
        return resp.json()

    async def register_player(
        self,
        *,
        telegram_id: int,
        telegram_username: str | None,
        phone: str,
        nickname: str,
        salutation: str,
        full_name: str,
        affiliation: str,
        can_play: bool,
        can_staff: bool,
    ) -> dict:
        resp = await self._request(
            "POST",
            "/api/bot/players/register",
            json={
                "telegram_id": telegram_id,
                "telegram_username": telegram_username,
                "phone": phone,
                "nickname": nickname,
                "salutation": salutation,
                "full_name": full_name,
                "affiliation": affiliation,
                "can_play": can_play,
                "can_staff": can_staff,
            },
        )
        return resp.json()

    async def update_profile(self, tg_id: int, **fields: Any) -> dict:
        resp = await self._request("PUT", f"/api/bot/players/me?telegram_id={tg_id}", json=fields)
        return resp.json()

    # ------------------------------------------------------------- sessions (user)
    async def list_game_days(self, tg_id: int, game_type: str | None = None) -> list[str]:
        params = {"telegram_id": tg_id}
        if game_type:
            params["game_type"] = game_type
        resp = await self._request("GET", "/api/bot/game-days", params=params)
        return resp.json()

    async def list_open_sessions(self, tg_id: int, game_type: str | None = None, day: str | None = None) -> list[dict]:
        params = {"telegram_id": tg_id}
        if game_type:
            params["game_type"] = game_type
        if day:
            params["day"] = day
        resp = await self._request("GET", "/api/bot/sessions/open", params=params)
        return resp.json()

    async def get_session(self, tg_id: int, session_id: int) -> dict | None:
        try:
            resp = await self._request("GET", f"/api/bot/sessions/{session_id}", params={"telegram_id": tg_id})
        except NotFoundError:
            return None
        return resp.json()

    async def register_for_session(
        self, tg_id: int, session_id: int, role_kind: str, available_from: str | None = None, available_until: str | None = None
    ) -> dict:
        resp = await self._request(
            "POST",
            f"/api/bot/sessions/{session_id}/register",
            json={
                "telegram_id": tg_id,
                "role_kind": role_kind,
                "available_from": available_from,
                "available_until": available_until,
            },
        )
        return resp.json()

    async def reserve_for_session(self, tg_id: int, session_id: int) -> dict:
        resp = await self._request(
            "POST", f"/api/bot/sessions/{session_id}/reserve", json={"telegram_id": tg_id}
        )
        return resp.json()

    async def cancel_registration(self, tg_id: int, session_id: int) -> dict:
        resp = await self._request(
            "DELETE", f"/api/bot/sessions/{session_id}/registration", params={"telegram_id": tg_id}
        )
        return resp.json()

    async def my_registrations(self, tg_id: int) -> list[dict]:
        resp = await self._request("GET", "/api/bot/registrations/mine", params={"telegram_id": tg_id})
        return resp.json()

    async def session_roster(self, tg_id: int, session_id: int) -> dict:
        resp = await self._request(
            "GET", f"/api/bot/sessions/{session_id}/roster", params={"telegram_id": tg_id}
        )
        return resp.json()

    # ------------------------------------------------------------- sessions (admin)
    async def admin_create_sessions_bulk(
        self, tg_id: int, starts_at_list: list[str], location: str, game_type: str
    ) -> list[int]:
        resp = await self._request(
            "POST",
            f"/api/bot/admin/sessions/bulk?telegram_id={tg_id}",
            json={
                "starts_at_list": [to_api_datetime(s) for s in starts_at_list],
                "location": location,
                "game_type": game_type,
            },
        )
        return resp.json()

    async def admin_check_conflicts(
        self, tg_id: int, starts_at_list: list[str], exclude_session_ids: list[int] | None = None
    ) -> list[str]:
        resp = await self._request(
            "POST",
            f"/api/bot/admin/sessions/check-conflicts?telegram_id={tg_id}",
            json={
                "starts_at_list": [to_api_datetime(s) for s in starts_at_list],
                "exclude_session_ids": exclude_session_ids or [],
            },
        )
        return [format_day_time(v) for v in resp.json()["conflicts"]]

    async def admin_day_cards(self, tg_id: int, game_type: str | None = None) -> list[dict]:
        params = {"telegram_id": tg_id}
        if game_type:
            params["game_type"] = game_type
        resp = await self._request("GET", "/api/bot/admin/sessions/day-cards", params=params)
        return resp.json()

    async def admin_sessions_by_day(self, tg_id: int, day: str) -> list[dict]:
        resp = await self._request(
            "GET", "/api/bot/admin/sessions/by-day", params={"telegram_id": tg_id, "day": day}
        )
        return resp.json()

    async def admin_update_session(self, tg_id: int, session_id: int, **fields: Any) -> dict:
        if "starts_at" in fields and fields["starts_at"]:
            fields["starts_at"] = to_api_datetime(fields["starts_at"])
        resp = await self._request(
            "PUT", f"/api/bot/admin/sessions/{session_id}?telegram_id={tg_id}", json=fields
        )
        return resp.json()

    async def admin_delete_session(self, tg_id: int, session_id: int) -> bool:
        try:
            await self._request("DELETE", f"/api/bot/admin/sessions/{session_id}", params={"telegram_id": tg_id})
        except NotFoundError:
            return False
        return True

    async def admin_sessions_pending_review(self, tg_id: int) -> list[dict]:
        resp = await self._request(
            "GET", "/api/bot/admin/sessions/pending-review", params={"telegram_id": tg_id}
        )
        return resp.json()

    # ------------------------------------------------------------- admin management
    async def admin_lookup_by_username(self, tg_id: int, username: str) -> dict | None:
        try:
            resp = await self._request(
                "GET", "/api/bot/admin/players/by-username", params={"telegram_id": tg_id, "username": username}
            )
        except NotFoundError:
            return None
        return resp.json()

    async def admin_lookup_by_phone(self, tg_id: int, phone: str) -> dict | None:
        try:
            resp = await self._request(
                "GET", "/api/bot/admin/players/by-phone", params={"telegram_id": tg_id, "phone": phone}
            )
        except NotFoundError:
            return None
        return resp.json()

    async def admin_list_admins(self, tg_id: int) -> list[dict]:
        resp = await self._request("GET", "/api/bot/admin/admins", params={"telegram_id": tg_id})
        return resp.json()

    async def admin_list_pending(self, tg_id: int) -> list[str]:
        resp = await self._request("GET", "/api/bot/admin/admins/pending", params={"telegram_id": tg_id})
        return resp.json()

    async def admin_grant(self, tg_id: int, *, target_telegram_id: int | None = None, username: str | None = None) -> dict:
        resp = await self._request(
            "POST",
            f"/api/bot/admin/admins?telegram_id={tg_id}",
            json={"telegram_id": target_telegram_id, "username": username},
        )
        return resp.json()

    async def admin_revoke(self, tg_id: int, target_telegram_id: int) -> bool:
        resp = await self._request(
            "DELETE", f"/api/bot/admin/admins/by-telegram/{target_telegram_id}", params={"telegram_id": tg_id}
        )
        return bool(resp.json().get("removed"))

    async def admin_revoke_pending(self, tg_id: int, username: str) -> bool:
        resp = await self._request(
            "DELETE", f"/api/bot/admin/admins/pending/{username}", params={"telegram_id": tg_id}
        )
        return bool(resp.json().get("removed"))
