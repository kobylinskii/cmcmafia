"""Рассылки, которые может сделать только бот -- у него один живёт токен Telegram.

Три независимые очереди, все устроены одинаково: бот забирает у API список
недоставленного, рассылает и подтверждает ack'ом. Пока ack не пришёл, строка
остаётся в очереди, так что упавший бот ничего не теряет.

- решения админа по заявкам на вступление  -> игроку   (раздел 3.7)
- решения админа по правкам профиля         -> игроку   (раздел 3.8)
- новые заявки и правки, ждущие проверки     -> админам  (admin_notification_service)

Очереди независимы: недоставленное в одной не задерживает другие.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound

from app import texts
from app.api_client import ApiClient

logger = logging.getLogger(__name__)

# Недоступный чат Telegram отдаёт не только как 403: на неизвестный чат приходит
# 400 с текстом "chat not found", и отдельного класса под такие ответы у aiogram
# нет -- отличить их от временной ошибки можно только по сообщению.
UNREACHABLE_CHAT_ERRORS = (
    "chat not found",
    "user is deactivated",
    "bot was blocked by the user",
    "peer_id_invalid",
)


def _is_unreachable_chat(exc: TelegramBadRequest) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in UNREACHABLE_CHAT_ERRORS)


CONFIRMED_TEXT = (
    "✅ Заявка подтверждена.\n\n"
    "Профиль виден на сайте, сыгранные игры идут в рейтинг."
)


def rejected_text(reason: str | None) -> str:
    return (
        "⛔ Заявка отклонена.\n\n"
        f"Причина: {reason or 'не указана'}\n\n"
        "Поправьте данные в разделе «👤 Профиль» и нажмите там "
        "«Отправить на повторную проверку»."
    )


def profile_change_text(item: dict) -> str:
    """Решение по правке профиля. Значение показывается целиком: человек мог
    отправить её давно и уже не помнить, что именно менял."""
    field = item.get("field_label") or "поле"
    value = item.get("new_value")
    shown = f"«{value}»" if value else "пустое значение"
    if item.get("status") == "applied":
        return f"✅ Изменение принято: {field} — теперь {shown}."
    return (
        f"⛔ Изменение отклонено: {field} → {shown}.\n\n"
        f"Причина: {item.get('rejection_reason') or 'не указана'}\n\n"
        "Прежнее значение осталось в силе. Можно поправить и отправить снова."
    )


def admin_registration_text(item: dict) -> str:
    """«Пришла новая заявка» для админа сайта. Ровно столько, чтобы решить, стоит
    ли открывать «Обзор» прямо сейчас, -- разбирается заявка всё равно там."""
    lines = [f"🆕 Новая заявка на вступление: {item.get('nickname') or 'без ника'}"]
    if item.get("full_name"):
        lines.append(f"ФИО: {item['full_name']}")
    affiliation = texts.AFFILIATION_SHORT.get(item.get("affiliation"))
    if affiliation:
        lines.append(f"Проход: {affiliation}")
    if item.get("telegram_username"):
        lines.append(f"Telegram: @{item['telegram_username']}")
    lines.append("\nПроверить — раздел «Обзор» в админке сайта.")
    return "\n".join(lines)


def admin_profile_change_text(item: dict) -> str:
    """«Игрок просит поправить профиль» для админа сайта."""
    field = item.get("field_label") or "поле"
    nickname = item.get("player_nickname") or "игрок"
    current = item.get("current_value") or "пусто"
    new_value = item.get("new_value") or "пусто"
    return (
        f"✏️ {nickname} просит поправить профиль — {field}\n"
        f"сейчас: {current}\n"
        f"станет: {new_value}\n\n"
        "Проверить — раздел «Обзор» в админке сайта."
    )


async def _deliver(bot: Bot, telegram_id: int, text: str) -> bool | None:
    """Отправить одно сообщение (общее для всех очередей: игроку и админу).

    True -- доставлено; False -- доставить не выйдет никогда (чат недоступен),
    строку можно подтверждать, иначе она обрабатывалась бы до конца времён;
    None -- временная ошибка, строка остаётся в очереди до следующего прохода.
    """
    try:
        await bot.send_message(telegram_id, text)
    except (TelegramForbiddenError, TelegramNotFound):
        # Адресат заблокировал бота или удалил аккаунт.
        logger.info("Чат %s недоступен, пропускаем", telegram_id)
        return False
    except TelegramBadRequest as exc:
        if not _is_unreachable_chat(exc):
            # 400 не про чат -- это ошибка в нашем же запросе, её надо видеть в
            # логах целиком, а сообщение доставить после починки.
            logger.warning("Не удалось отправить сообщение в чат %s", telegram_id, exc_info=True)
            return None
        # Тот же безнадёжный случай, что и 403 выше, только оформленный
        # Telegram'ом как 400.
        logger.info("Чат %s недоступен (%s), пропускаем", telegram_id, exc.message)
        return False
    except Exception:
        # Сеть, лимиты Telegram, что угодно временное.
        logger.warning("Не удалось отправить сообщение в чат %s", telegram_id, exc_info=True)
        return None
    return True


async def deliver_once(bot: Bot, api: ApiClient) -> int:
    """Один проход по очереди решений о вступлении. Возвращает число доставленных."""
    queue = await api.confirmation_notifications()
    if not queue:
        return 0

    acked: list[int] = []
    delivered = 0
    for item in queue:
        status = item.get("confirmation_status")
        text = CONFIRMED_TEXT if status == "confirmed" else rejected_text(item.get("rejection_reason"))
        outcome = await _deliver(bot, item["telegram_id"], text)
        if outcome is None:
            continue
        acked.append(item["player_id"])
        delivered += int(outcome)

    if acked:
        await api.ack_confirmations(acked)
    return delivered


async def deliver_profile_changes_once(bot: Bot, api: ApiClient) -> int:
    """Один проход по очереди решений о правках профиля."""
    queue = await api.profile_change_notifications()
    if not queue:
        return 0

    acked: list[int] = []
    delivered = 0
    for item in queue:
        outcome = await _deliver(bot, item["telegram_id"], profile_change_text(item))
        if outcome is None:
            continue
        acked.append(item["change_id"])
        delivered += int(outcome)

    if acked:
        await api.ack_profile_changes(acked)
    return delivered


async def _deliver_to_admins(bot: Bot, recipients: list[int], text: str) -> bool:
    """Разослать одно уведомление всем админам сразу.

    True -- у каждого получателя исход окончательный (доставлено или чат
    недоступен), событие можно подтверждать. False -- у кого-то временная
    ошибка: повторим на следующем проходе. Тем, кто уже получил, уйдёт
    повторно -- админов единицы, а точный учёт «кому дошло» не стоит второй
    таблицы.
    """
    resolved = True
    for telegram_id in recipients:
        if await _deliver(bot, telegram_id, text) is None:
            resolved = False
    return resolved


async def deliver_admin_notifications_once(bot: Bot, api: ApiClient) -> int:
    """Один проход по очереди оповещения админов сайта.

    Возвращает число разосланных событий (заявок и правок), а не сообщений.
    """
    data = await api.admin_notifications()
    recipients = data.get("recipients") or []
    registrations = data.get("registrations") or []
    profile_changes = data.get("profile_changes") or []
    if not recipients or (not registrations and not profile_changes):
        # Писать некому либо не о чем. Очередь не трогаем: в отличие от рассылок
        # игрокам, где недоставленное можно пометить безнадёжным, здесь адресат
        # (админ с привязанным Telegram) может появиться позже.
        return 0

    acked_registrations = [
        item["player_id"]
        for item in registrations
        if await _deliver_to_admins(bot, recipients, admin_registration_text(item))
    ]
    acked_changes = [
        item["change_id"]
        for item in profile_changes
        if await _deliver_to_admins(bot, recipients, admin_profile_change_text(item))
    ]

    if acked_registrations or acked_changes:
        await api.ack_admin_notifications(
            registration_player_ids=acked_registrations,
            profile_change_ids=acked_changes,
        )
    return len(acked_registrations) + len(acked_changes)


async def notifier_loop(bot: Bot, api: ApiClient, interval_seconds: int) -> None:
    while True:
        for name, deliver in (
            ("решений по заявкам", deliver_once),
            ("решений по правкам профиля", deliver_profile_changes_once),
            ("новых заявок и правок админам", deliver_admin_notifications_once),
        ):
            try:
                sent = await deliver(bot, api)
                if sent:
                    logger.info("Разослано %s: %s", name, sent)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Фоновая задача не имеет права уронить бота: API может быть
                # временно недоступен, следующая итерация просто повторит попытку.
                # Падение одной очереди не должно останавливать вторую.
                logger.exception("Проход рассылки %s не удался", name)
        await asyncio.sleep(interval_seconds)
