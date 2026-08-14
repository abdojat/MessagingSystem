"""Shared bounded checkpoint orchestration for CLI and periodic execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.merkle_checkpointer_config import MerkleCheckpointerSettings
from app.services.merkle_audit_service import MerkleAuditService, MerkleIntegrityError


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckpointBatchResult:
    sequence_no: int
    leaf_count: int
    merkle_root: str


@dataclass(frozen=True)
class CheckpointCycleResult:
    batches: tuple[CheckpointBatchResult, ...] = ()

    @property
    def batch_count(self) -> int:
        return len(self.batches)

    @property
    def event_count(self) -> int:
        return sum(batch.leaf_count for batch in self.batches)


async def checkpoint_pending_events(
    db: AsyncSession,
    *,
    max_leaves: int,
    signing_key_id: str,
    private_key_base64: str,
    public_keys: Mapping[str, str],
    all_pending: bool = True,
) -> CheckpointCycleResult:
    """Commit eligible events in bounded batches using the existing Merkle service."""

    created: list[CheckpointBatchResult] = []
    while True:
        try:
            batch = await MerkleAuditService.create_checkpoint(
                db,
                max_leaves=max_leaves,
                signing_key_id=signing_key_id,
                private_key_base64=private_key_base64,
                public_keys=public_keys,
            )
            if batch is None:
                await db.rollback()
                break
            result = CheckpointBatchResult(
                sequence_no=batch.sequence_no,
                leaf_count=batch.leaf_count,
                merkle_root=batch.merkle_root,
            )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

        created.append(result)
        if not all_pending:
            break

    return CheckpointCycleResult(tuple(created))


async def run_checkpoint_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    settings: MerkleCheckpointerSettings,
) -> CheckpointCycleResult:
    async with session_factory() as db:
        return await checkpoint_pending_events(
            db,
            max_leaves=settings.audit_merkle_batch_size,
            signing_key_id=settings.audit_merkle_signing_key_id,
            private_key_base64=settings.audit_merkle_signing_private_key.get_secret_value(),
            public_keys=settings.audit_merkle_public_keys,
            all_pending=True,
        )


async def wait_for_next_cycle(stop_event: asyncio.Event, interval_seconds: int) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
    except TimeoutError:
        pass


CycleRunner = Callable[
    [async_sessionmaker[AsyncSession], MerkleCheckpointerSettings],
    Awaitable[CheckpointCycleResult],
]
IntervalWaiter = Callable[[asyncio.Event, int], Awaitable[None]]


async def run_periodic_checkpointer(
    settings: MerkleCheckpointerSettings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    stop_event: asyncio.Event,
    cycle_runner: CycleRunner = run_checkpoint_cycle,
    interval_waiter: IntervalWaiter = wait_for_next_cycle,
) -> None:
    """Run immediately, then periodically; retry transient infrastructure failures."""

    if not settings.audit_merkle_checkpoint_enabled:
        logger.info("Automatic Merkle checkpointing is disabled")
        return

    while not stop_event.is_set():
        logger.info("Merkle checkpoint cycle started")
        try:
            result = await cycle_runner(session_factory, settings)
        except MerkleIntegrityError:
            logger.exception("Merkle checkpoint cycle stopped on an integrity failure")
            raise
        except (SQLAlchemyError, OSError) as exc:
            # Database exception text can contain connection details. Log only
            # the bounded exception type and retry on the next normal interval.
            logger.warning(
                "Merkle checkpoint cycle failed transiently (%s); retrying next cycle",
                type(exc).__name__,
            )
        else:
            if result.batch_count == 0:
                logger.info("No pending audit events")
            else:
                for batch in result.batches:
                    logger.info(
                        "Merkle checkpoint #%s created: leaves=%s root=%s",
                        batch.sequence_no,
                        batch.leaf_count,
                        batch.merkle_root,
                    )
                logger.info(
                    "Merkle checkpoint cycle completed: batches=%s events=%s",
                    result.batch_count,
                    result.event_count,
                )

        if stop_event.is_set():
            break
        await interval_waiter(stop_event, settings.audit_merkle_checkpoint_interval_seconds)

