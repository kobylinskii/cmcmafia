"""Уведомление админов сайта о новых заявках и правках профиля

Раньше о новой заявке на вступление или правке профиля админ узнавал, только
если сам зашёл на вкладку «Обзор». Теперь бот раз в минуту забирает у API
очередь новых pending-строк и пишет о них админам сайта в Telegram (токен
бота живёт только у бота, поэтому доставка — опросом, как и решения игрокам).

Очередь = pending-строка, о которой админам ещё не написали. Признак «написали»
— отдельная метка времени: у заявки `players.confirmation_admin_notified_at`,
у правки `player_profile_changes.admin_notified_at`. Ставит её бот `ack`'ом
после рассылки; пока метки нет, строка остаётся в очереди, так что упавший бот
ничего не теряет. Повторная подача заявки (`resubmit`) метку снимает — это
новое событие для админа.

Revision ID: b4e8d1a7f230
Revises: c9a2f4e17b58
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4e8d1a7f230"
down_revision: Union[str, None] = "c9a2f4e17b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column("confirmation_admin_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "player_profile_changes",
        sa.Column("admin_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Обе очереди читаются ботом на каждом проходе (раз в минуту): частичные
    # индексы держат их дешёвыми независимо от размера таблиц.
    op.create_index(
        "idx_players_pending_admin_unnotified",
        "players",
        ["created_at"],
        postgresql_where=sa.text(
            "confirmation_status = 'pending' AND confirmation_admin_notified_at IS NULL"
        ),
    )
    op.create_index(
        "idx_profile_changes_admin_unnotified",
        "player_profile_changes",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending' AND admin_notified_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_profile_changes_admin_unnotified", table_name="player_profile_changes")
    op.drop_index("idx_players_pending_admin_unnotified", table_name="players")
    op.drop_column("player_profile_changes", "admin_notified_at")
    op.drop_column("players", "confirmation_admin_notified_at")
