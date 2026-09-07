"""Доставка решений админа: по заявкам на вступление и по правкам профиля.

Бэкенд в Telegram не пишет: токен бота живёт только здесь, и заводить его
второй копией в API ради одного сообщения значило бы расширять поверхность
утечки. Поэтому доставка устроена опросом -- бот забирает у API очередь
принятых решений, рассылает их и подтверждает доставку ack'ом. Пока ack не
пришёл, решение остаётся в очереди, так что упавший бот ничего не теряет.

Очередей две, и они независимы: недоставленное решение по заявке не должно
задерживать ответ по правке профиля, и наоборот.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound

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


async def _deliver(bot: Bot, telegram_id: int, text: str) -> bool | None:
    """Отправить одно сообщение.

    True -- доставлено; False -- доставить не выйдет никогда (чат недоступен),
    и решение надо подтвердить, иначе оно будет обрабатываться до конца времён;
    None -- временная ошибка, строка остаётся в очереди до следующего прохода.
    """
    try:
        await bot.send_message(telegram_id, text)
    except (TelegramForbiddenError, TelegramNotFound):
        # Человек заблокировал бота или удалил аккаунт.
        logger.info("Игрок %s недоступен, помечаем решение доставленным", telegram_id)
        return False
    except TelegramBadRequest as exc:
        if not _is_unreachable_chat(exc):
            # 400 не про чат -- это ошибка в нашем же запросе, её надо видеть в
            # логах целиком, а решение доставить после починки.
            logger.warning("Не удалось отправить решение игроку %s", telegram_id, exc_info=True)
            return None
        # Тот же безнадёжный случай, что и 403 выше, только оформленный
        # Telegram'ом как 400.
        logger.info("Игрок %s недоступен (%s), помечаем решение доставленным", telegram_id, exc.message)
        return False
    except Exception:
        # Сеть, лимиты Telegram, что угодно временное.
        logger.warning("Не удалось отправить решение игроку %s", telegram_id, exc_info=True)
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


async def notifier_loop(bot: Bot, api: ApiClient, interval_seconds: int) -> None:
    while True:
        for name, deliver in (
            ("решений по заявкам", deliver_once),
            ("решений по правкам профиля", deliver_profile_changes_once),
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
