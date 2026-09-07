"""games.day_reminder_sent_at -- напоминание «сегодня игры»

Метка стоит на ПЕРВОЙ игре клубного дня: напоминание одно на день, а не на
каждый слот, и «уже отправлено» естественнее всего хранить там же, где
считается время отправки (за REMINDER_LEAD_HOURS до начала первой игры).

Revision ID: f1a7c3d90b42
Revises: e7c4b9a2f318
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a7c3d90b42"
down_revision: Union[str, None] = "e7c4b9a2f318"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "games", sa.Column("day_reminder_sent_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("games", "day_reminder_sent_at")
