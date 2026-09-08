"""tournament_awards.created_at -> NOT NULL

Ровно то же расхождение модели и схемы, что уже чинила миграция e7c4b9a2f318
для player_profile_changes: `TournamentAward.created_at: Mapped[datetime]`
подразумевает NOT NULL, а миграция d81f5c3ae604 завела колонку без него
(остальные created_at в схеме -- NOT NULL). NULL'ов там нет и не было:
server_default now() стоит с самого создания таблицы, поэтому ALTER безопасен
без бэкфилла.

Чтобы это не всплыло третий раз, расхождение теперь ловит тест
tests/test_schema_drift.py: он сравнивает метаданные моделей с реальной
схемой и падает на любой невыраженной в миграциях разнице.

Revision ID: f4a2b8e91c07
Revises: d81f5c3ae604
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f4a2b8e91c07"
down_revision: Union[str, None] = "d81f5c3ae604"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("tournament_awards", "created_at", nullable=False)


def downgrade() -> None:
    op.alter_column("tournament_awards", "created_at", nullable=True)
