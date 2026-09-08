"""player_profile_changes.field += 'photo_url' -- фото тоже ждёт админа

Аватарка из бота раньше вставала в профиль сразу, минуя очередь: фото на
странице игрока -- такая же публичная часть профиля, как ник и ФИО, и
подтверждённый участник не меняет её молча (раздел 3.8).

В new_value у этого поля лежит не введённый текст, а адрес уже записанного
файла (/media/players/<uuid>.jpg): показать админу картинку иначе нечем.

Revision ID: a3f6d1c74e02
Revises: f1a7c3d90b42
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a3f6d1c74e02"
down_revision: Union[str, None] = "f1a7c3d90b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None

_OLD = "field IN ('full_name','nickname','age','experience','bio')"
_NEW = "field IN ('full_name','nickname','age','experience','bio','photo_url')"


def upgrade() -> None:
    op.drop_constraint("ck_profile_changes_field_enum", "player_profile_changes", type_="check")
    op.create_check_constraint("ck_profile_changes_field_enum", "player_profile_changes", _NEW)


def downgrade() -> None:
    # Строки с фото откатом не переживут: под старым ограничением их нет места.
    op.execute("DELETE FROM player_profile_changes WHERE field = 'photo_url'")
    op.drop_constraint("ck_profile_changes_field_enum", "player_profile_changes", type_="check")
    op.create_check_constraint("ck_profile_changes_field_enum", "player_profile_changes", _OLD)
