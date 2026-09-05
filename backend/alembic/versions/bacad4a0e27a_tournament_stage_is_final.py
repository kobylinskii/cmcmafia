"""tournament stage is_final

Revision ID: bacad4a0e27a
Revises: e2272f17b915
Create Date: 2026-09-05 17:25:56.801140

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bacad4a0e27a'
down_revision: Union[str, None] = 'e2272f17b915'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default вместо двухшаговой миграции: у существующих этапов
    # финального ещё не было, false -- единственный разумный бэкофилл, и
    # он же нужен постоянно (Boolean NOT NULL без дефолта на уровне БД
    # означал бы, что любой будущий прямой INSERT в обход ORM обязан
    # знать про это поле).
    op.add_column(
        'tournament_stages',
        sa.Column('is_final', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('tournament_stages', 'is_final')
