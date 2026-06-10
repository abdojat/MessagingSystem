import argparse
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _read_dotenv_value(name: str) -> str | None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def _running_inside_container() -> bool:
    return Path("/.dockerenv").exists()


def _prepare_local_database_url() -> None:
    if os.environ.get("DATABASE_URL"):
        return
    database_url = _read_dotenv_value("DATABASE_URL")
    if not database_url:
        database_url = "postgresql+asyncpg://postgres:postgres@postgres:5432/channels"
    if not _running_inside_container():
        database_url = database_url.replace("@postgres:", "@127.0.0.1:").replace("@postgres/", "@127.0.0.1/")
    os.environ["DATABASE_URL"] = database_url


_prepare_local_database_url()

from app.db.models import Event  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.event_integrity_service import (  # noqa: E402
    HASH_ALGORITHM,
    INTEGRITY_VERSION,
    EventIntegrityService,
    compute_event_hash,
)


def _has_existing_hash(event: Event) -> bool:
    return event.event_hash is not None


def _assign_integrity(event: Event, scope: str, previous_hash: str | None, *, dry_run: bool) -> str:
    original = (
        event.previous_hash,
        event.hash_algorithm,
        event.integrity_version,
        event.integrity_scope,
    )
    event.previous_hash = previous_hash
    event.hash_algorithm = HASH_ALGORITHM
    event.integrity_version = INTEGRITY_VERSION
    event.integrity_scope = scope
    event_hash = compute_event_hash(event)
    if dry_run:
        (
            event.previous_hash,
            event.hash_algorithm,
            event.integrity_version,
            event.integrity_scope,
        ) = original
    else:
        event.event_hash = event_hash
    return event_hash


async def backfill_event_integrity(*, force: bool, dry_run: bool, scope_filter: str | None) -> dict[str, int]:
    async with SessionLocal() as db:
        rows = await db.execute(select(Event).order_by(Event.created_at.asc(), Event.id.asc()))
        groups: dict[str, list[Event]] = defaultdict(list)
        for event in rows.scalars().all():
            scope = EventIntegrityService.scope_for_event(event.channel_id)
            if scope_filter and scope != scope_filter:
                continue
            groups[scope].append(event)

        stats = {
            "scopes": 0,
            "events_seen": 0,
            "events_updated": 0,
            "existing_kept": 0,
            "conflicts": 0,
        }

        for scope in sorted(groups.keys()):
            stats["scopes"] += 1
            previous_hash: str | None = None
            await EventIntegrityService.lock_scope(db, scope)

            for event in groups[scope]:
                stats["events_seen"] += 1
                has_existing = _has_existing_hash(event)

                if has_existing and not force:
                    is_valid_existing = (
                        event.integrity_scope == scope
                        and event.hash_algorithm == HASH_ALGORITHM
                        and event.integrity_version == INTEGRITY_VERSION
                        and event.previous_hash == previous_hash
                        and event.event_hash == compute_event_hash(event)
                    )
                    if not is_valid_existing:
                        stats["conflicts"] += 1
                        break
                    previous_hash = event.event_hash
                    stats["existing_kept"] += 1
                    continue

                event_hash = _assign_integrity(event, scope, previous_hash, dry_run=dry_run)
                previous_hash = event_hash
                stats["events_updated"] += 1

        if dry_run:
            await db.rollback()
        else:
            await db.commit()
        return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill tamper-evident hash-chain metadata for event logs.")
    parser.add_argument("--force", action="store_true", help="Rebuild existing non-null integrity fields.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without committing.")
    parser.add_argument("--scope", help="Limit to one scope, for example channel:<uuid> or system.")
    args = parser.parse_args()

    stats = asyncio.run(backfill_event_integrity(force=args.force, dry_run=args.dry_run, scope_filter=args.scope))
    mode = "dry run" if args.dry_run else "committed"
    print(f"Event integrity backfill {mode}:")
    for key, value in stats.items():
        print(f"- {key}: {value}")
    if stats["conflicts"] and not args.force:
        print("- note: existing integrity metadata was left unchanged; rerun with --force to rebuild conflicted scopes.")


if __name__ == "__main__":
    main()
