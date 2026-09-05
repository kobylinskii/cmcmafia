"""tournaments

Revision ID: fffc59fca625
Revises: 182ab644c300
Create Date: 2026-09-04 14:10:09.636108

Турнир как отдельная сущность (название/описание/место) + ссылка на него из
games. Ограничение «турнирная игра обязана принадлежать турниру» проверяется
только для оценённых игр: сессию в боте заводят задолго до того, как известен
турнир, и требовать его на этапе записи означало бы сломать бота.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'fffc59fca625'
down_revision: Union[str, None] = '182ab644c300'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = "fk_games_tournament_id"
CK_NAME = "ck_games_rated_tournament_has_tournament"

# Куда сложить уже существующие оценённые турнирные игры: без турнира они
# нарушили бы новый констрейнт, а выдумывать за админа настоящие турниры
# миграция не вправе. Строка создаётся только если такие игры реально есть.
LEGACY_SLUG = "arhivnye-igry"
LEGACY_NAME = "Архивные игры"
LEGACY_DESCRIPTION = (
    "Игры, внесённые до появления турниров в системе. "
    "Разнесите их по настоящим турнирам и удалите этот раздел."
)


def upgrade() -> None:
    op.create_table(
        'tournaments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('location', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$'", name='ck_tournaments_slug_format'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('slug'),
    )
    op.add_column('games', sa.Column('tournament_id', sa.Integer(), nullable=True))
    op.create_index('idx_games_tournament', 'games', ['tournament_id'], unique=False)
    op.create_foreign_key(
        FK_NAME, 'games', 'tournaments', ['tournament_id'], ['id'], ondelete='RESTRICT'
    )

    # Бэкфилл до установки констрейнта, иначе он не пройдёт на живой базе.
    op.execute(sa.text(f"""
        INSERT INTO tournaments (slug, name, description)
        SELECT '{LEGACY_SLUG}', '{LEGACY_NAME}', '{LEGACY_DESCRIPTION}'
        WHERE EXISTS (
            SELECT 1 FROM games
            WHERE status = 'rated' AND game_type = 'tournament' AND tournament_id IS NULL
        )
    """))
    op.execute(sa.text(f"""
        UPDATE games SET tournament_id = (SELECT id FROM tournaments WHERE slug = '{LEGACY_SLUG}')
        WHERE status = 'rated' AND game_type = 'tournament' AND tournament_id IS NULL
    """))

    op.create_check_constraint(
        CK_NAME,
        'games',
        "status <> 'rated' OR game_type <> 'tournament' OR tournament_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(CK_NAME, 'games', type_='check')
    op.drop_constraint(FK_NAME, 'games', type_='foreignkey')
    op.drop_index('idx_games_tournament', table_name='games')
    op.drop_column('games', 'tournament_id')
    op.drop_table('tournaments')
