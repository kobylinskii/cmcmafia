"""Модерация правок профиля, приходящих из бота

Профиль игрока -- это ФИО в списке на пропуск и ник в рейтинге и составах,
то есть то, по чему человека узнают в клубе. Раньше подтверждённый игрок
переписывал их из бота молча, и админ узнавал об этом только по расхождению
списка на пропуск с документами.

Теперь правка текстового поля ложится сюда и ждёт решения админа, а в самом
профиле продолжает действовать прежнее значение. Строка живёт и после
решения: 'applied'/'rejected' -- это история правок, а заодно очередь
доставки решения игроку (decided_at заполнен, notified_at нет), устроенная
ровно как у модерации регистраций.

Кнопочные поля (обращение, статус прохода, роли, любимая роль) в эту таблицу
не попадают -- варианты там задаёт сам бот, проверять нечего.

Revision ID: d5b81ea3f047
Revises: c3f5a91d7e20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5b81ea3f047"
down_revision: Union[str, None] = "c3f5a91d7e20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_profile_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(length=20), nullable=False),
        # NULL -- осознанная очистка необязательного поля, а не «правки нет»:
        # сам факт правки задаётся наличием строки.
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending','applied','rejected')",
            name="ck_profile_changes_status_enum",
        ),
        sa.CheckConstraint(
            "field IN ('full_name','nickname','age','experience','bio')",
            name="ck_profile_changes_field_enum",
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR rejection_reason IS NOT NULL",
            name="ck_profile_changes_rejected_has_reason",
        ),
    )
    # Одно поле -- одна очередь: повторная правка того же поля заменяет
    # прежнюю, иначе админ разбирал бы стопку промежуточных вариантов.
    op.create_index(
        "uq_profile_changes_one_pending_per_field",
        "player_profile_changes",
        ["player_id", "field"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("idx_profile_changes_status", "player_profile_changes", ["status"])


def downgrade() -> None:
    op.drop_index("idx_profile_changes_status", table_name="player_profile_changes")
    op.drop_index("uq_profile_changes_one_pending_per_field", table_name="player_profile_changes")
    op.drop_table("player_profile_changes")
