"""Reassign data from the legacy seeded user to a real account.

Run this once after enabling auth:

    uv run python scripts/claim_legacy_data.py --email you@example.com --apply
"""

from __future__ import annotations

import argparse

from app.config import get_settings
from app.db.models import Meeting, User
from app.db.session import SessionLocal, configure_engine, init_db
from sqlalchemy import func, select, update


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Target account email (must exist)")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry run)")
    args = parser.parse_args()

    settings = get_settings()
    configure_engine(settings.database_url)
    init_db(settings)

    with SessionLocal() as db:
        legacy = db.scalar(select(User).where(User.email == settings.default_user_email))
        target = db.scalar(select(User).where(User.email == args.email))
        if target is None:
            print(f"No account found for {args.email}. Register it first.")
            return 1
        if legacy is None or legacy.id == target.id:
            print("No legacy user data to claim.")
            return 0

        count = db.scalar(
            select(func.count()).select_from(Meeting).where(Meeting.user_id == legacy.id)
        )
        print(f"Legacy user: {legacy.email} ({legacy.id})")
        print(f"Target user: {target.email} ({target.id})")
        print(f"Meetings to reassign: {count}")

        if not args.apply:
            print("Dry run. Re-run with --apply to write changes.")
            return 0

        db.execute(
            update(Meeting).where(Meeting.user_id == legacy.id).values(user_id=target.id)
        )
        if not target.discord_webhook_url and legacy.discord_webhook_url:
            target.discord_webhook_url = legacy.discord_webhook_url

        remaining = db.scalar(
            select(func.count()).select_from(Meeting).where(Meeting.user_id == legacy.id)
        )
        if remaining == 0:
            db.delete(legacy)
            print("Deleted the legacy user.")
        db.commit()
        print(f"Reassigned {count} meeting(s) to {target.email}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
