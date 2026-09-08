"""Схема в миграциях обязана совпадать с моделями.

Дважды одно и то же расхождение уже доезжало до продакшна: created_at,
объявленный в модели как `Mapped[datetime]` (то есть NOT NULL), миграция
заводила без ограничения -- сперва у player_profile_changes (чинила
e7c4b9a2f318), потом у tournament_awards (f4a2b8e91c07). Ни один тест этого
не видел: SQLAlchemy молча пишет в такую колонку и на чтении не спотыкается.

Здесь то же сравнение, что делает `alembic revision --autogenerate`, только
без генерации файла: если модели и схема разошлись, тест печатает конкретную
разницу.
"""

from __future__ import annotations

from alembic.autogenerate import produce_migrations
from alembic.migration import MigrationContext

from app.database import Base, engine

# Служебная таблица самого alembic: в моделях её нет и быть не должно.
IGNORED_TABLES = {"alembic_version"}


def _diffs() -> list:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "include_object": lambda obj, name, type_, reflected, compare_to: not (
                    type_ == "table" and name in IGNORED_TABLES
                ),
            },
        )
        script = produce_migrations(context, Base.metadata)
    # upgrade_ops.as_diffs() отдаёт плоский список кортежей вида
    # ('add_column', schema, table, Column) -- пустой, когда расхождений нет.
    return script.upgrade_ops.as_diffs()


def test_models_match_migrated_schema() -> None:
    diffs = _diffs()
    assert not diffs, (
        "Модели разошлись с тем, что накатывают миграции. "
        "Нужна миграция на каждую строку ниже:\n  "
        + "\n  ".join(repr(d) for d in diffs)
    )
