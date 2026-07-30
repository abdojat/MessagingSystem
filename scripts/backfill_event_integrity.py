import argparse
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
# Run this conditional step only when `str(BACKEND_DIR) not in sys.path` is true.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DOCKER_DRY_RUN_COMMAND = (
    'docker compose exec backend sh -lc '
    '"cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py --dry-run"'
)
DOCKER_BACKFILL_COMMAND = (
    'docker compose exec backend sh -lc '
    '"cd /app && PYTHONPATH=/app python scripts/backfill_event_integrity.py"'
)


# Reads dotenv value; the command-line verification workflow uses it.
def _read_dotenv_value(name: str) -> str | None:
    env_path = ROOT / ".env"
    # Return early when `not env_path.exists()` because the remaining work is not applicable.
    if not env_path.exists():
        return None
    # Process each `line` from `env_path.read_text(encoding='utf-8').splitlines()` to apply this step to the full collection.
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        # Skip the current item when `not stripped or stripped.startswith('#') or '=' not in stripped` and continue processing the rest.
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        # Return early when `key.strip() == name` because the remaining work is not applicable.
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


# Implements the running inside container operation; the command-line verification workflow uses it.
def _running_inside_container() -> bool:
    return Path("/.dockerenv").exists()


# Implements the host adjusted database url operation; the command-line verification workflow uses it.
def _host_adjusted_database_url(database_url: str) -> str:
    # Return early when `_running_inside_container()` because the remaining work is not applicable.
    if _running_inside_container():
        return database_url
    return database_url.replace("@postgres:", "@127.0.0.1:").replace("@postgres/", "@127.0.0.1/")


# Masks database url; the command-line verification workflow uses it.
def _mask_database_url(database_url: str) -> str:
    # Return early when `'://' not in database_url or '@' not in database_url` because the remaining work is not applicable.
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    # Run this conditional step only when `':' in credentials` is true.
    if ":" in credentials:
        user, _ = credentials.split(":", 1)
        return f"{scheme}://{user}:***@{host}"
    return f"{scheme}://***@{host}"


# Prepares local database url; the command-line verification workflow uses it.
def _prepare_local_database_url() -> None:
    database_url = (
        os.environ.get("EVENT_INTEGRITY_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or _read_dotenv_value("DATABASE_URL")
    )
    # Run this conditional step only when `not database_url` is true.
    if not database_url:
        database_url = "postgresql+asyncpg://postgres:postgres@postgres:5432/channels"
    os.environ["DATABASE_URL"] = _host_adjusted_database_url(database_url)


_prepare_local_database_url()

from app.db.models import Event  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.event_integrity_service import (  # noqa: E402
    HASH_ALGORITHM,
    INTEGRITY_VERSION,
    EventIntegrityService,
    compute_event_hash,
)


# Checks for existing hash; the command-line verification workflow uses it.
def _has_existing_hash(event: Event) -> bool:
    return event.event_hash is not None


# Assigns integrity; the command-line verification workflow uses it.
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
    # Choose the appropriate path based on whether `dry_run` is true.
    if dry_run:
        (
            event.previous_hash,
            event.hash_algorithm,
            event.integrity_version,
            event.integrity_scope,
        ) = original
    # Handle the alternate path after the preceding branch or loop does not produce a result.
    else:
        event.event_hash = event_hash
    return event_hash


# Backfills event integrity; the command-line verification workflow uses it.
async def backfill_event_integrity(*, force: bool, dry_run: bool, scope_filter: str | None) -> dict[str, int]:
    # Keep `SessionLocal()` active while this scoped operation is performed.
    async with SessionLocal() as db:
        rows = await db.execute(select(Event).order_by(Event.created_at.asc(), Event.id.asc()))
        groups: dict[str, list[Event]] = defaultdict(list)
        # Process each `event` from `rows.scalars().all()` to apply this step to the full collection.
        for event in rows.scalars().all():
            scope = EventIntegrityService.scope_for_event(event.channel_id)
            # Skip the current item when `scope_filter and scope != scope_filter` and continue processing the rest.
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

        # Process each `scope` from `sorted(groups.keys())` to apply this step to the full collection.
        for scope in sorted(groups.keys()):
            stats["scopes"] += 1
            previous_hash: str | None = None
            await EventIntegrityService.lock_scope(db, scope)

            # Process each `event` from `groups[scope]` to apply this step to the full collection.
            for event in groups[scope]:
                stats["events_seen"] += 1
                has_existing = _has_existing_hash(event)

                # Run this conditional step only when `has_existing and (not force)` is true.
                if has_existing and not force:
                    is_valid_existing = (
                        event.integrity_scope == scope
                        and event.hash_algorithm == HASH_ALGORITHM
                        and event.integrity_version == INTEGRITY_VERSION
                        and event.previous_hash == previous_hash
                        and event.event_hash == compute_event_hash(event)
                    )
                    # Run this conditional step only when `not is_valid_existing` is true.
                    if not is_valid_existing:
                        stats["conflicts"] += 1
                        break
                    previous_hash = event.event_hash
                    stats["existing_kept"] += 1
                    continue

                event_hash = _assign_integrity(event, scope, previous_hash, dry_run=dry_run)
                previous_hash = event_hash
                stats["events_updated"] += 1

        # Choose the appropriate path based on whether `dry_run` is true.
        if dry_run:
            await db.rollback()
        # Handle the alternate path after the preceding branch or loop does not produce a result.
        else:
            await db.commit()
        return stats


# Runs the module's command-line workflow; the command-line verification workflow uses it.
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill tamper-evident hash-chain metadata for event logs.",
        epilog=(
            "Demo-safe Docker dry-run: "
            f"{DOCKER_DRY_RUN_COMMAND}\n"
            "Demo-safe Docker real backfill: "
            f"{DOCKER_BACKFILL_COMMAND}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--force", action="store_true", help="Rebuild existing non-null integrity fields.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without committing.")
    parser.add_argument("--scope", help="Limit to one scope, for example channel:<uuid> or system.")
    args = parser.parse_args()

    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        stats = asyncio.run(backfill_event_integrity(force=args.force, dry_run=args.dry_run, scope_filter=args.scope))
    # Handle `Exception` here so this workflow can recover or report the failure consistently.
    except Exception as exc:
        print("Event integrity backfill failed.", file=sys.stderr)
        print(f"- error: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"- DATABASE_URL used: {_mask_database_url(os.environ.get('DATABASE_URL', ''))}", file=sys.stderr)
        print(
            "- hint: host execution needs PostgreSQL credentials that match the database exposed on localhost.",
            file=sys.stderr,
        )
        print("- demo-safe Docker dry-run:", file=sys.stderr)
        print(f"  {DOCKER_DRY_RUN_COMMAND}", file=sys.stderr)
        print("- demo-safe Docker real backfill:", file=sys.stderr)
        print(f"  {DOCKER_BACKFILL_COMMAND}", file=sys.stderr)
        raise SystemExit(1) from exc
    mode = "dry run" if args.dry_run else "committed"
    print(f"Event integrity backfill {mode}:")
    # Process each `(key, value)` from `stats.items()` to apply this step to the full collection.
    for key, value in stats.items():
        print(f"- {key}: {value}")
    # Run this conditional step only when `stats['conflicts'] and (not args.force)` is true.
    if stats["conflicts"] and not args.force:
        print("- note: existing integrity metadata was left unchanged; rerun with --force to rebuild conflicted scopes.")


# Run this conditional step only when `__name__ == '__main__'` is true.
if __name__ == "__main__":
    main()
