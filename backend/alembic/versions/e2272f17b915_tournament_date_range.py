"""tournament date range

Revision ID: e2272f17b915
Revises: 06f9718d4967
Create Date: 2026-09-05 16:12:46.063443

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2272f17b915'
down_revision: Union[str, None] = '06f9718d4967'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CK_NAME = "ck_tournaments_ends_after_starts"


def upgrade() -> None:
    # Nullable сперва, чтобы было куда бэкфиллить уже существующие турниры --
    # NOT NULL накатывается отдельным шагом ниже.
    op.add_column('tournaments', sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tournaments', sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True))
    # У существующих турниров реального периода проведения ещё не было --
    # ставим created_at как единственный разумный плейсхолдер, дальше это
    # правится вручную через форму турнира.
    op.execute(
        "UPDATE tournaments SET starts_at = created_at, ends_at = created_at "
        "WHERE starts_at IS NULL OR ends_at IS NULL"
    )
    op.alter_column('tournaments', 'starts_at', nullable=False)
    op.alter_column('tournaments', 'ends_at', nullable=False)
    op.create_check_constraint(CK_NAME, 'tournaments', 'ends_at >= starts_at')


def downgrade() -> None:
    op.drop_constraint(CK_NAME, 'tournaments', type_='check')
    op.drop_column('tournaments', 'ends_at')
    op.drop_column('tournaments', 'starts_at')
