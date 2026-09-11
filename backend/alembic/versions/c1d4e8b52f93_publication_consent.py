"""players.publication_consent -- согласие на публикацию профиля

Revision ID: c1d4e8b52f93
Revises: a9c2e5b71d34
Create Date: 2026-09-11

Существующим игрокам ставим true: они регистрировались, когда профиль был
публичным по умолчанию, и их карточки уже опубликованы. Менять это молча --
значит снести с сайта весь рейтинг разом.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d4e8b52f93"
down_revision: Union[str, None] = "a9c2e5b71d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column(
            "publication_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("players", "publication_consent")
