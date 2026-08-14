"""Long-running isolated process for automatic signed Merkle checkpoints."""

from __future__ import annotations

import asyncio
import signal

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.logging import configure_logging
from app.core.merkle_checkpointer_config import MerkleCheckpointerSettings
from app.services.merkle_audit_service import MerkleIntegrityError
from app.services.merkle_checkpoint_service import run_periodic_checkpointer


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except NotImplementedError:  # Windows fallback for local development.
            signal.signal(signum, lambda *_args: loop.call_soon_threadsafe(stop_event.set))


async def _run(settings: MerkleCheckpointerSettings) -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    try:
        await run_periodic_checkpointer(settings, session_factory, stop_event=stop_event)
    finally:
        await engine.dispose()


def main() -> None:
    try:
        settings = MerkleCheckpointerSettings()
    except (ValidationError, ValueError) as exc:
        raise SystemExit(f"Merkle checkpointer configuration failed: {exc}") from None

    configure_logging(settings.log_level)
    try:
        asyncio.run(_run(settings))
    except MerkleIntegrityError as exc:
        raise SystemExit(f"Merkle checkpointer stopped on integrity failure [{exc.code}]: {exc}") from None
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
