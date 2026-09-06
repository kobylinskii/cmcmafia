"""Модерация регистраций из бота + клубные настройки

Регистрация в боте открыта кому угодно: раньше новый человек мгновенно
попадал и в рейтинг, и в список игроков на сайте. Теперь запись из бота
заводится в статусе 'pending' и до решения админа не видна на публичной
части (см. app/services/visibility.py); записываться на игры она при этом
может сразу.

Все уже существующие игроки объявляются подтверждёнными: они попали в базу
до появления модерации, и прятать их с сайта задним числом нельзя. Ровно для
этого server_default столбца -- 'confirmed', а не 'pending': и бэкфилл, и
любой игрок, заведённый админом на сайте, оказываются подтверждёнными без
дополнительного кода, а 'pending' проставляет явно только ручка регистрации
из бота.

club_settings -- единственная строка с рубежом пропускной недели (день и
время, когда список ФИО на пропуск переключается на следующую неделю).

Revision ID: c3f5a91d7e20
Revises: a1c4f7e29b03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3f5a91d7e20"
down_revision: Union[str, None] = "a1c4f7e29b03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column(
            "confirmation_status",
            sa.String(length=20),
            nullable=False,
            server_default="confirmed",
        ),
    )
    op.add_column("players", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column(
        "players", sa.Column("confirmation_decided_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "players", sa.Column("confirmation_notified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_players_confirmation_status_enum",
        "players",
        "confirmation_status IN ('pending','confirmed','rejected')",
    )
    op.create_check_constraint(
        "ck_players_rejected_has_reason",
        "players",
        "confirmation_status <> 'rejected' OR rejection_reason IS NOT NULL",
    )
    op.create_index(
        "idx_players_pending_confirmation",
        "players",
        ["created_at"],
        postgresql_where=sa.text("confirmation_status = 'pending'"),
    )
    op.create_index(
        "idx_players_confirmation_unnotified",
        "players",
        ["confirmation_decided_at"],
        postgresql_where=sa.text(
            "confirmation_decided_at IS NOT NULL AND confirmation_notified_at IS NULL"
        ),
    )

    op.create_table(
        "club_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "pass_week_rollover_weekday", sa.SmallInteger(), nullable=False, server_default="6"
        ),
        sa.Column(
            "pass_week_rollover_time", sa.String(length=5), nullable=False, server_default="18:00"
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("id = 1", name="ck_club_settings_singleton"),
        sa.CheckConstraint(
            "pass_week_rollover_weekday BETWEEN 0 AND 6",
            name="ck_club_settings_rollover_weekday_range",
        ),
        sa.CheckConstraint(
            r"pass_week_rollover_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'",
            name="ck_club_settings_rollover_time_format",
        ),
    )
    # Строка создаётся здесь, а не лениво в сервисе: настройка читается на
    # каждом открытии «Обзора», и ленивая вставка означала бы запись в БД из
    # GET-ручки под конкурентными запросами.
    op.execute("INSERT INTO club_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")


def downgrade() -> None:
    op.drop_table("club_settings")
    op.drop_index("idx_players_confirmation_unnotified", table_name="players")
    op.drop_index("idx_players_pending_confirmation", table_name="players")
    op.drop_constraint("ck_players_rejected_has_reason", "players", type_="check")
    op.drop_constraint("ck_players_confirmation_status_enum", "players", type_="check")
    op.drop_column("players", "confirmation_notified_at")
    op.drop_column("players", "confirmation_decided_at")
    op.drop_column("players", "rejection_reason")
    op.drop_column("players", "confirmation_status")
