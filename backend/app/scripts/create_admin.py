"""One-off CLI to create the very first site admin.

There's deliberately no HTTP endpoint for this: granting site access is
itself an admin-only action (POST /api/admin/players/{id}/site-access), so
the very first admin has to come from somewhere with direct DB access. Run
this once per deployment, then manage further admins through the web panel.

Usage (inside the api container):
    docker compose exec api python -m app.scripts.create_admin --nickname "Admin"
    docker compose exec api python -m app.scripts.create_admin --player-id 1
    docker compose exec api python -m app.scripts.create_admin --nickname "Admin" --username root --password "..."
"""

from __future__ import annotations

import argparse
import sys

from app.database import SessionLocal
from app.services import player_service, slug_service
from app.services.player_service import PlayerValidationError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--player-id", type=int, help="Promote an existing player (e.g. one who registered via the bot) instead of creating a new one.")
    parser.add_argument("--nickname", help="Nickname for a new player (ignored with --player-id).")
    parser.add_argument("--slug", help="Slug for a new player; auto-suggested from --nickname if omitted.")
    parser.add_argument("--username", help="Site login; defaults to the player's slug.")
    parser.add_argument("--password", help="Site password; a random one is generated and printed if omitted.")
    args = parser.parse_args()

    if not args.player_id and not args.nickname:
        parser.error("provide either --player-id (existing player) or --nickname (new player)")

    db = SessionLocal()
    try:
        if args.player_id:
            from app import models

            player = db.get(models.Player, args.player_id)
            if player is None:
                print(f"No player with id={args.player_id}", file=sys.stderr)
                return 1
        else:
            slug = args.slug or slug_service.suggest_slug(args.nickname, db)
            try:
                player = player_service.create_player(db, nickname=args.nickname, slug=slug)
            except PlayerValidationError as exc:
                print(f"Could not create player: {exc.message}", file=sys.stderr)
                return 1

        username = args.username or player.slug
        try:
            if args.password:
                from app import security

                player.site_username = username
                player.site_password_hash = security.hash_password(args.password)
                player.is_site_admin = True
                db.commit()
                temp_password = args.password
            else:
                temp_password = player_service.grant_site_access(db, player=player, username=username)
                db.commit()
        except PlayerValidationError as exc:
            print(f"Could not grant access: {exc.message}", file=sys.stderr)
            return 1

        print("Site admin ready:")
        print(f"  player_id: {player.id}")
        print(f"  nickname:  {player.nickname}")
        print(f"  username:  {username}")
        print(f"  password:  {temp_password}")
        print("\nLog in at /admin/login, then change the password by re-running this")
        print("script with --player-id and a new --password.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
