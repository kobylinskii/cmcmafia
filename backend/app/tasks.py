"""Фоновые задачи API.

Пока одна: перевод прошедших игр в статус 'played' (ARCHITECTURE.md, раздел 8,
шаг 2). Без неё игра, созданная ботом, навсегда остаётся 'scheduled',
GET /api/admin/games/pending-review всегда возвращает пусто, и весь цикл
«запись в боте -> напоминание -> оценка на сайте» не работает вообще.

Задача живёт внутри процесса API, а не в боте: статус игры -- это состояние
данных, а не сообщение в Telegram, и переводить его должен единственный
писатель в БД. Бот только опрашивает pending-review и рассылает напоминания.
"""

from __future__ import annotations

import asyncio
import logging

from app.database import SessionLocal
from app.services import game_service

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 300


def sweep_past_sessions() -> int:
    """Один прогон. Синхронный (SQLAlchemy-сессия блокирующая), вызывается из
    цикла через asyncio.to_thread, чтобы не блокировать event loop."""
    db = SessionLocal()
    try:
        moved = game_service.mark_past_sessions_as_played(db)
        db.commit()
        return moved
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def sweep_loop() -> None:
    while True:
        try:
            moved = await asyncio.to_thread(sweep_past_sessions)
            if moved:
                logger.info("Прошедших игр переведено в 'played': %s", moved)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Фоновая задача не имеет права уронить процесс: БД может быть
            # временно недоступна, следующая итерация просто повторит попытку.
            logger.exception("Не удалось перевести прошедшие игры в 'played'")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
