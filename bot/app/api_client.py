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


def now_local() -> datetime:
    """Текущий момент в клубной зоне.

    Единственный способ узнать «сейчас» в боте. Наивный datetime.now() сравнивался
    с московским временем игр и в контейнере с UTC уводил границу «прошедшая
    игра / предстоящая» на три часа: только что записавшийся игрок видел свою
    вечернюю игру в списке завершённых.
    """
    return datetime.now(LOCAL_TZ)


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
            # telegram_id дублируется в query специально: сервер читает
            # действующего пользователя из тела, но rate limit считается по
            # query-параметру (тело в key-функции недоступно). Без дубля весь
            # трафик бота лимитировался бы по одному IP на всех сразу --
            # см. backend/app/rate_limit.py.
            params={"telegram_id": telegram_id},
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

    async def my_stats(self, tg_id: int) -> dict:
        resp = await self._request("GET", "/api/bot/players/me/stats", params={"telegram_id": tg_id})
        return resp.json()

    async def resubmit_profile(self, tg_id: int) -> dict:
        resp = await self._request(
            "POST", "/api/bot/players/me/resubmit", params={"telegram_id": tg_id}
        )
        return resp.json()

    # --------------------------------------------------- модерация регистраций
    async def confirmation_notifications(self) -> list[dict]:
        """Решения админа по заявкам, о которых игрок ещё не знает.

        Ручка сервисная: действующего пользователя у неё нет, авторизует её
        один лишь BOT_SERVICE_TOKEN -- рассылает бот целиком, а не кто-то из
        своего диалога.
        """
        resp = await self._request("GET", "/api/bot/players/confirmation-notifications")
        return resp.json()

    async def ack_confirmations(self, player_ids: list[int]) -> int:
        resp = await self._request(
            "POST",
            "/api/bot/players/confirmation-notifications/ack",
            json={"player_ids": player_ids},
        )
        return int(resp.json().get("marked", 0))

    async def profile_change_notifications(self) -> list[dict]:
        """Решения админа по правкам профиля. Ручка сервисная, как и очередь
        решений по заявкам выше."""
        resp = await self._request("GET", "/api/bot/players/profile-change-notifications")
        return resp.json()

    async def ack_profile_changes(self, change_ids: list[int]) -> int:
        resp = await self._request(
            "POST",
            "/api/bot/players/profile-change-notifications/ack",
            json={"change_ids": change_ids},
        )
        return int(resp.json().get("marked", 0))

    # ------------------------------------------- оповещение админов сайта
    async def admin_notifications(self) -> dict:
        """Что появилось на проверку и кому из админов сайта об этом написать.

        Ручка сервисная: действующего пользователя у неё нет, авторизует её
        один BOT_SERVICE_TOKEN -- рассылает бот целиком.
        """
        resp = await self._request("GET", "/api/bot/admin-notifications")
        return resp.json()

    async def ack_admin_notifications(
        self, *, registration_player_ids: list[int], profile_change_ids: list[int]
    ) -> dict:
        resp = await self._request(
            "POST",
            "/api/bot/admin-notifications/ack",
            json={
                "registration_player_ids": registration_player_ids,
                "profile_change_ids": profile_change_ids,
            },
        )
        return resp.json()

    # ------------------------------------------------- решения админа из бота
    # Кнопки под тем самым сообщением, которым бот сообщил о новом событии:
    # админ клуба живёт в боте, и лишний вход в админку сайта откладывал
    # проверку на сутки. Ручки требуют прав админа (telegram_id действующего),
    # а не только сервисного токена.
    async def moderation_queue(self, tg_id: int) -> dict:
        """Всё, что ждёт решения, -- раздел «На проверке» в админ-меню.

        Не то же, что admin_notifications: та очередь пустеет после ack'а, а
        уведомление можно удалить из чата.
        """
        resp = await self._request(
            "GET", "/api/bot/moderation/pending", params={"telegram_id": tg_id}
        )
        return resp.json()

    async def moderate_registration(
        self, tg_id: int, player_id: int, *, reason: str | None = None
    ) -> dict:
        decision = "reject" if reason is not None else "confirm"
        resp = await self._request(
            "POST",
            f"/api/bot/moderation/registrations/{player_id}/{decision}",
            params={"telegram_id": tg_id},
            json={"reason": reason} if reason is not None else None,
        )
        return resp.json()

    async def moderate_profile_change(
        self, tg_id: int, change_id: int, *, reason: str | None = None
    ) -> dict:
        decision = "reject" if reason is not None else "apply"
        resp = await self._request(
            "POST",
            f"/api/bot/moderation/profile-changes/{change_id}/{decision}",
            params={"telegram_id": tg_id},
            json={"reason": reason} if reason is not None else None,
        )
        return resp.json()

    # ------------------------------------------------ напоминания о дне игр
    async def day_reminders(self) -> list[dict]:
        """Дни, до первой игры которых осталось меньше трёх часов. Ручка
        сервисная, как и остальные очереди рассылок."""
        resp = await self._request("GET", "/api/bot/day-reminders")
        return resp.json()

    async def ack_day_reminders(self, game_ids: list[int]) -> int:
        resp = await self._request(
            "POST", "/api/bot/day-reminders/ack", json={"game_ids": game_ids}
        )
        return int(resp.json().get("marked", 0))

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
            params={"telegram_id": tg_id},  # для rate limit, см. register_player
            json={
                "telegram_id": tg_id,
                "role_kind": role_kind,
                "available_from": available_from,
                "available_until": available_until,
            },
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

    # -------------------------------------------------------------- рассылки
    async def admin_weekly_broadcast(self, tg_id: int, days: int = 7) -> dict:
        """Игры ближайшей недели и список тех, кому анонс ещё актуален."""
        resp = await self._request(
            "GET", "/api/bot/admin/broadcast/weekly", params={"telegram_id": tg_id, "days": days}
        )
        return resp.json()

    async def admin_broadcast_audience(self, tg_id: int) -> dict:
        """Получатели произвольного сообщения: весь клуб, кроме отклонённых.

        Отдельно от анонса: там записавшиеся вычитаются, здесь -- нет.
        """
        resp = await self._request(
            "GET", "/api/bot/admin/broadcast/audience", params={"telegram_id": tg_id}
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
