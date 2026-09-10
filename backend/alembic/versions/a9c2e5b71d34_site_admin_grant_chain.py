"""players.site_admin_granted_by_id -- цепочка выдачи прав админа сайта

Отзыв прав стал иерархическим: снять доступ можно только с того, кому ты его
выдал сам -- напрямую или по цепочке (player_service.ensure_can_manage_site_admin).
Для этого нужно помнить, кто кого назначил.

Бэкфилла нет намеренно: у всех, кто уже админ на момент миграции, колонка
остаётся NULL, то есть они корневые -- ровно как первый админ из
scripts/create_admin.py. Снять права с корневого может только он сам; кому-то
надо быть неприкосновенным, иначе цепочку можно замкнуть на себя.

ON DELETE SET NULL: жёсткое удаление игрока (player_service.delete_player)
не должно упираться в ссылку. Осиротеть цепочка при этом не успевает --
delete_player перед удалением перевешивает «детей» на того, кто выдал права
самому удаляемому.

Revision ID: a9c2e5b71d34
Revises: f4a2b8e91c07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9c2e5b71d34"
down_revision: Union[str, None] = "f4a2b8e91c07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("players", sa.Column("site_admin_granted_by_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "players_site_admin_granted_by_id_fkey",
        "players",
        "players",
        ["site_admin_granted_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("players_site_admin_granted_by_id_fkey", "players", type_="foreignkey")
    op.drop_column("players", "site_admin_granted_by_id")
