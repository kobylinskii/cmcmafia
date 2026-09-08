"""tournament awards

Revision ID: d81f5c3ae604
Revises: a3f6d1c74e02
Create Date: 2026-09-08 17:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd81f5c3ae604'
down_revision: Union[str, None] = 'a3f6d1c74e02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Флаг публикации блока номинаций. server_default -- по той же причине, что
    # и у tournament_stages.is_final (миграция bacad4a0e27a): у существующих
    # турниров номинаций не было, false -- единственный разумный бэкофилл.
    op.add_column(
        'tournaments',
        sa.Column('awards_published', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Только РУЧНЫЕ правки победителей: посчитанные номинации в базе не живут
    # (см. awards_service.compute_awards).
    op.create_table(
        'tournament_awards',
        sa.Column('tournament_id', sa.Integer(), nullable=False),
        sa.Column('nomination', sa.String(length=20), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('tournament_id', 'nomination'),
        sa.CheckConstraint(
            "nomination IN ('best_citizen','best_mafia','best_don','best_sheriff','mvp',"
            "'first_place','second_place','third_place')",
            name='ck_tournament_awards_nomination_enum',
        ),
    )


def downgrade() -> None:
    op.drop_table('tournament_awards')
    op.drop_column('tournaments', 'awards_published')
