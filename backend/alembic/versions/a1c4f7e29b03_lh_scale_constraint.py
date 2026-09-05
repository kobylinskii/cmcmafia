"""Сузить lh до реальной шкалы попаданий ЛХ

Поле хранит ПОПАДАНИЯ («сколько из трёх названных оказались чёрными»), а не
баллы: 0 / 0.5 / 1 / 1.5 == 0/3, 1/3, 2/3, 3/3. Старый констрейнт разрешал
любое значение в диапазоне 0..1.5 включительно, тогда как таблица баллов
(rating_service.LH_POINTS) знает ровно эти четыре точки и на всё остальное
молча отдаёт ноль. Значение вроде 0.75, попавшее в базу мимо API, давало ноль
баллов без ошибки и не попадало ни в одну корзину распределения ЛХ на
странице игрока.

Revision ID: a1c4f7e29b03
Revises: bacad4a0e27a
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a1c4f7e29b03"
down_revision: Union[str, None] = "bacad4a0e27a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Значения вне шкалы округляем к ближайшей ступени вниз -- иначе строки,
    # уже лежащие в базе, не дадут навесить констрейнт. Начисленные за них
    # баллы от этого не меняются: LH_POINTS.get() и так возвращал по ним ноль.
    op.execute(
        """
        UPDATE game_participants
           SET lh = CASE
                      WHEN lh IS NULL THEN NULL
                      WHEN lh >= 1.5 THEN 1.5
                      WHEN lh >= 1.0 THEN 1.0
                      WHEN lh >= 0.5 THEN 0.5
                      ELSE 0
                    END
         WHERE lh IS NOT NULL AND lh NOT IN (0, 0.5, 1, 1.5)
        """
    )
    op.execute("ALTER TABLE game_participants DROP CONSTRAINT IF EXISTS ck_participants_lh_range")
    op.execute(
        """
        ALTER TABLE game_participants
          ADD CONSTRAINT ck_participants_lh_scale
          CHECK (lh IS NULL OR lh IN (0, 0.5, 1, 1.5))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE game_participants DROP CONSTRAINT IF EXISTS ck_participants_lh_scale")
    op.execute(
        """
        ALTER TABLE game_participants
          ADD CONSTRAINT ck_participants_lh_range
          CHECK (lh IS NULL OR (lh >= 0 AND lh <= 1.5))
        """
    )
