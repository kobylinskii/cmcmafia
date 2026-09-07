"""Пересчёт рейтинга всей истории по текущей формуле.

Обычно это происходит само: `rating_service.recompute_all()` вызывается при
любом create/update/delete рейтинговой игры. Отдельная команда нужна ровно в
одном случае -- когда изменилась САМА ФОРМУЛА (веса, коэффициенты, состав Sa).
Тогда игры никто не трогал, а числа в `player_rating` посчитаны по старой
формуле и останутся такими, пока кто-нибудь не отредактирует случайную игру.

Пересчёт полный и идемпотентный: он удаляет `player_rating` и
`player_rating_history` целиком и строит их заново по всем играм со
статусом 'rated'. Игры и составы не трогаются.

Usage (внутри контейнера api):
    docker compose exec api python -m app.scripts.recompute_rating
    docker compose exec api python -m app.scripts.recompute_rating --dry-run
"""

from __future__ import annotations

import argparse

from app import models
from app.database import SessionLocal
from app.services import rating_service


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Посчитать и показать, что изменится, но не записывать в базу.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        before = {
            r.player_id: float(r.rating) for r in db.query(models.PlayerRating).all()
        }

        result = rating_service.recompute_all(db)
        db.flush()

        after = {
            r.player_id: float(r.rating) for r in db.query(models.PlayerRating).all()
        }
        nicknames = {
            p.id: p.nickname
            for p in db.query(models.Player)
            .filter(models.Player.id.in_(after.keys() | before.keys()))
            .all()
        }

        changed = [
            (nicknames.get(pid, f"id={pid}"), before.get(pid), new)
            for pid, new in after.items()
            if before.get(pid) is None or abs(before[pid] - new) >= 0.01
        ]

        print(f"Игр в реплее:      {result.games_processed}")
        print(f"Игроков затронуто: {result.players_affected}")
        print(f"Рейтинг изменился: {len(changed)}")
        if changed:
            print()
            for nickname, old, new in sorted(changed, key=lambda c: -abs((c[2] - (c[1] or 0)))):
                was = f"{old:.2f}" if old is not None else "—"
                print(f"  {nickname:<20} {was:>10} -> {new:>8.2f}")

        if args.dry_run:
            db.rollback()
            print("\n--dry-run: ничего не записано.")
        else:
            db.commit()
            print("\nГотово, рейтинг записан.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
