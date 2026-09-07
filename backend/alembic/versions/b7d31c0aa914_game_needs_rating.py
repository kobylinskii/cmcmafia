"""games.needs_rating

Revision ID: b7d31c0aa914
Revises: d5b81ea3f047
Create Date: 2026-09-07 10:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d31c0aa914'
down_revision: Union[str, None] = 'd5b81ea3f047'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # true -- единственный корректный бэкофилл: до этой колонки любая
    # не-турнирная игра рано или поздно оценивалась, другого флоу не
    # существовало. server_default оставлен насовсем, чтобы прямой INSERT
    # в обход ORM (тесты, ручные правки) не обязан был знать про поле.
    op.add_column(
        'games',
        sa.Column('needs_rating', sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column('games', 'needs_rating')
