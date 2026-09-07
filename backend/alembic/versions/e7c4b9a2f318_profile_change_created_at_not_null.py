"""player_profile_changes.created_at -> NOT NULL

Расхождение модели и схемы: `PlayerProfileChange.created_at: Mapped[datetime]`
подразумевает NOT NULL, а миграция d5b81ea3f047 завела колонку без него
(остальные created_at в схеме -- NOT NULL). NULL'ов там нет и не было:
server_default now() стоит с самого начала, поэтому ALTER безопасен без
бэкфилла.

Revision ID: e7c4b9a2f318
Revises: b4e8d1a7f230
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e7c4b9a2f318"
down_revision: Union[str, None] = "b4e8d1a7f230"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("player_profile_changes", "created_at", nullable=False)


def downgrade() -> None:
    op.alter_column("player_profile_changes", "created_at", nullable=True)
