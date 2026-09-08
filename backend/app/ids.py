"""Границы числовых идентификаторов, приходящих из URL.

FastAPI разбирает `game_id: int` в питоновский int произвольной длины, а в
базе это `integer` (4 байта). Всё, что не влезло, доезжало до драйвера и
падало там как «integer out of range» -- то есть посетитель, открывший
/api/games/99999999999999999999, получал 500 вместо 404, и то же самое было
на 70 операциях API разом. Идентификатора такой величины не бывает по
построению, поэтому это отказ на входе, а не ошибка запроса.

telegram_id хранится в BIGINT (`players.telegram_id`), у него своя граница.
Нижняя оставлена симметричной: у пользователей Telegram id положительный, но
у чатов бывает отрицательный, и сужать это здесь незачем -- задача типа
только в том, чтобы значение вообще влезло в колонку.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Path, Query

PG_INT_MAX = 2**31 - 1
PG_BIGINT_MIN, PG_BIGINT_MAX = -(2**63), 2**63 - 1

# Первичный ключ из пути: SERIAL нумеруется с единицы.
DbId = Annotated[int, Path(ge=1, le=PG_INT_MAX)]
# Тот же ключ, но пришедший query-параметром.
DbIdQuery = Annotated[int, Query(ge=1, le=PG_INT_MAX)]

TelegramId = Annotated[int, Query(ge=PG_BIGINT_MIN, le=PG_BIGINT_MAX)]
TelegramIdPath = Annotated[int, Path(ge=PG_BIGINT_MIN, le=PG_BIGINT_MAX)]
