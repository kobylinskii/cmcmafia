"""Единый критерий «этого игрока видно на публичной части сайта».

Публичных мест, где перечисляются игроки, несколько -- рейтинг, список
игроков, карточка по slug, счётчики на главной, ранг внутри статистики
игрока. Условие у всех одно и то же, и когда оно жило копипастой в пяти
запросах, добавление модерации регистраций означало пять шансов забыть один
из них. Здесь оно одно.
"""

from __future__ import annotations

from app import models


def public_player_criteria() -> tuple:
    """Критерии для .filter(*public_player_criteria()) по таблице players.

    is_active -- мягкое удаление (игрок ушёл из клуба, но его игры в истории
    остались). confirmation_status -- модерация регистрации из бота: пока
    админ не подтвердил новичка, его на сайте нет вообще (см.
    models.ConfirmationStatus). publication_consent -- отзыв согласия на
    публикацию: игрок остаётся в клубе, но своей карточки на сайте не хочет.

    Именно поэтому условие живёт одной функцией: отзыв согласия обязан
    срабатывать везде сразу, а не в тех местах, где о нём вспомнили.
    """
    return (
        models.Player.is_active.is_(True),
        models.Player.confirmation_status == models.ConfirmationStatus.confirmed.value,
        models.Player.publication_consent.is_(True),
    )
