"""Шкала баллов ЛХ существует в трёх копиях -- на Python, на SQL и на
TypeScript. Раньше синхронность держалась только на комментариях «держать в
синхроне»: разъехавшись, копии дали бы разные баллы в рейтинге, в среднем
балле и в колонке «ЛХ» на странице игры, причём молча.
"""

from __future__ import annotations

import pathlib
import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app import models
from app.database import SessionLocal
from app.services import game_service, rating_service, stats_service

SCALE = [0.0, 0.5, 1.0, 1.5]


def test_sql_lh_table_matches_python():
    """Настоящее выражение stats_service._LH_POINTS_SQL, посчитанное настоящим
    Postgres на настоящих строках, даёт то же, что rating_service.lh_points().

    Считается именно объект из модуля, а не переписанная в тест копия: если
    таблица баллов разъедется между Python и SQL, тест упадёт.
    """
    db = SessionLocal()
    try:
        players = [
            models.Player(nickname=f"ЛХ-тест-{i}", slug=f"lh-test-{i}") for i in range(len(SCALE))
        ]
        db.add_all(players)
        db.flush()
        game = models.Game(
            starts_at=datetime.now(timezone.utc), game_type="funky", status="played"
        )
        db.add(game)
        db.flush()
        for seat, (raw, player) in enumerate(zip(SCALE, players), start=1):
            db.add(
                models.GameParticipant(
                    game_id=game.id,
                    player_id=player.id,
                    seat_number=seat,
                    role="citizen",
                    lh=raw,
                )
            )
        db.flush()

        rows = db.execute(
            select(models.GameParticipant.lh, stats_service._LH_POINTS_SQL)
            .where(models.GameParticipant.game_id == game.id)
            .order_by(models.GameParticipant.seat_number)
        ).all()

        assert len(rows) == len(SCALE)
        for raw, sql_points in rows:
            expected = rating_service.lh_points(float(raw))
            assert float(sql_points) == expected, (
                f"ЛХ {raw}: SQL даёт {sql_points}, Python -- {expected}"
            )
    finally:
        # Тест ничего не оставляет в базе: он про согласованность выражений,
        # а не про данные.
        db.rollback()
        db.close()


def test_typescript_lh_scale_matches_python():
    """frontend/src/types/api.ts LH_SCALE == rating_service.LH_POINTS."""
    ts = pathlib.Path(__file__).resolve().parents[2] / "frontend/src/types/api.ts"
    if not ts.exists():  # бэкенд может разворачиваться отдельно от фронта
        pytest.skip("frontend/src/types/api.ts недоступен")

    block = re.search(r"LH_SCALE[^=]*=\s*\[(.*?)\];", ts.read_text(), re.S)
    assert block, "LH_SCALE не найден в types/api.ts"

    entries = re.findall(r"raw:\s*([\d.]+).*?points:\s*([\d.]+)", block.group(1), re.S)
    assert len(entries) == len(SCALE), f"в LH_SCALE {len(entries)} ступеней, ожидалось {len(SCALE)}"

    for raw_str, points_str in entries:
        raw, points = float(raw_str), float(points_str)
        assert points == rating_service.lh_points(raw), (
            f"ЛХ {raw}: TypeScript даёт {points}, Python -- {rating_service.lh_points(raw)}"
        )


def test_validator_accepts_exactly_the_scale():
    """Валидатор состава и таблица баллов знают одни и те же ступени."""
    assert game_service.VALID_LH_VALUES == set(SCALE)
    assert set(rating_service.LH_POINTS) == set(SCALE)
