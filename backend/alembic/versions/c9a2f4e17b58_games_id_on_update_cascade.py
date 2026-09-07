"""FK на games.id -- ON UPDATE CASCADE (перенумерация игр по дате)

Игры нумеруются по дате проведения и без дыр: удалили непроведённую игру --
остальные сдвинулись, добавили игру задним числом -- она встала на своё место
в хронологии (game_service.resequence_game_ids). Это означает UPDATE games.id,
а значит все ссылающиеся строки должны переезжать вместе с ним.

ON DELETE CASCADE у этих внешних ключей уже был; добавляется только ON UPDATE.

Revision ID: c9a2f4e17b58
Revises: b7d31c0aa914
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c9a2f4e17b58"
down_revision: Union[str, None] = "b7d31c0aa914"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Все таблицы со ссылкой на games.id. Имена самих ограничений в начальной
# миграции не задавались, поэтому их выдал Postgres (games_id_fkey-подобные);
# ниже они ищутся в каталоге, а не пишутся строкой -- на базе, поднятой
# другой версией alembic, имя может отличаться.
_CHILD_TABLES = ("game_participants", "registrations", "reserves", "player_rating_history")


def _rebuild(on_update: str) -> None:
    for table in _CHILD_TABLES:
        op.execute(
            f"""
            DO $$
            DECLARE
                fk_name text;
            BEGIN
                SELECT con.conname INTO fk_name
                FROM pg_constraint con
                JOIN pg_class child ON child.oid = con.conrelid
                JOIN pg_class parent ON parent.oid = con.confrelid
                WHERE con.contype = 'f'
                  AND child.relname = '{table}'
                  AND parent.relname = 'games'
                LIMIT 1;

                IF fk_name IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', fk_name);
                END IF;

                ALTER TABLE {table}
                    ADD CONSTRAINT {table}_game_id_fkey
                    FOREIGN KEY (game_id) REFERENCES games (id)
                    ON DELETE CASCADE {on_update};
            END
            $$;
            """
        )


def upgrade() -> None:
    _rebuild("ON UPDATE CASCADE")


def downgrade() -> None:
    _rebuild("")
