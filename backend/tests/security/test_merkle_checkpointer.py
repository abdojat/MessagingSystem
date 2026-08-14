import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.merkle_checkpointer_config import MerkleCheckpointerSettings
from app.db import merkle_tool
from app.db.models import AuditMerkleBatch, AuditMerkleLeaf
from app.services.admin_service import AdminService
from app.services.event_service import log_event
from app.services.merkle_audit_service import MerkleAuditService, generate_ed25519_keypair, verify_proof_bundle
from app.services.merkle_checkpoint_service import (
    CheckpointCycleResult,
    run_checkpoint_cycle,
    run_periodic_checkpointer,
)


@pytest.fixture
def signing_values():
    private_key, public_key = generate_ed25519_keypair()
    return "audit-checkpointer-test", private_key, {"audit-checkpointer-test": public_key}


def _settings(signing_values, **overrides) -> MerkleCheckpointerSettings:
    key_id, private_key, public_keys = signing_values
    values = {
        "audit_merkle_checkpoint_enabled": True,
        "audit_merkle_checkpoint_interval_seconds": 60,
        "audit_merkle_batch_size": 256,
        "audit_merkle_signing_key_id": key_id,
        "audit_merkle_signing_private_key": private_key,
        "audit_merkle_public_keys": public_keys,
    }
    values.update(overrides)
    return MerkleCheckpointerSettings(**values)


class _ExistingSessionFactory:
    """Exercise a real DB session without closing the fixture-owned session."""

    def __init__(self, session):
        self.session = session

    def __call__(self):
        session = self.session

        class _Context:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                return False

        return _Context()


async def _events(db_session, count: int, prefix: str):
    events = [await log_event(db_session, f"{prefix}.{index}", {"index": index}) for index in range(count)]
    await db_session.commit()
    return events


@pytest.mark.asyncio
async def test_disabled_checkpointer_does_not_run_a_cycle(signing_values):
    settings = _settings(signing_values, audit_merkle_checkpoint_enabled=False)
    stop_event = asyncio.Event()
    calls = 0

    async def runner(_session_factory, _settings):
        nonlocal calls
        calls += 1
        return CheckpointCycleResult()

    await run_periodic_checkpointer(settings, object(), stop_event=stop_event, cycle_runner=runner)

    assert calls == 0


@pytest.mark.asyncio
async def test_valid_pending_events_are_checkpointed_and_proof_still_verifies(db_session, signing_values):
    events = await _events(db_session, 4, "automatic.valid")
    proof_event_id = events[2].id
    settings = _settings(signing_values)

    result = await run_checkpoint_cycle(_ExistingSessionFactory(db_session), settings)
    proof = await MerkleAuditService.proof_for_event(
        db_session,
        proof_event_id,
        public_keys=signing_values[2],
    )

    assert result.batch_count == 1
    assert result.event_count == 4
    assert verify_proof_bundle(proof, signing_values[2])["valid"] is True


@pytest.mark.asyncio
async def test_no_pending_events_is_a_successful_noop(db_session, signing_values):
    await _events(db_session, 2, "automatic.noop")
    settings = _settings(signing_values)
    factory = _ExistingSessionFactory(db_session)

    first = await run_checkpoint_cycle(factory, settings)
    second = await run_checkpoint_cycle(factory, settings)

    assert first.event_count == 2
    assert second == CheckpointCycleResult()


@pytest.mark.asyncio
async def test_automatic_cycle_uses_multiple_bounded_batches(db_session, signing_values):
    await _events(db_session, 5, "automatic.bounded")
    settings = _settings(signing_values, audit_merkle_batch_size=2)

    result = await run_checkpoint_cycle(_ExistingSessionFactory(db_session), settings)

    assert [batch.leaf_count for batch in result.batches] == [2, 2, 1]
    assert list((await db_session.execute(select(AuditMerkleBatch.sequence_no))).scalars()) == [1, 2, 3]
    assert len(list((await db_session.execute(select(AuditMerkleLeaf.event_id))).scalars())) == 5


def test_checkpoint_interval_is_parsed_from_environment(monkeypatch):
    monkeypatch.setenv("AUDIT_MERKLE_CHECKPOINT_INTERVAL_SECONDS", "60")

    environment_settings = MerkleCheckpointerSettings(
        audit_merkle_checkpoint_enabled=False,
    )

    assert environment_settings.audit_merkle_checkpoint_interval_seconds == 60


@pytest.mark.parametrize("interval", [0, 9, 86_401, "not-a-number"])
def test_invalid_checkpoint_interval_is_rejected(interval):
    with pytest.raises(ValidationError, match="audit_merkle_checkpoint_interval_seconds"):
        MerkleCheckpointerSettings(
            audit_merkle_checkpoint_enabled=False,
            audit_merkle_checkpoint_interval_seconds=interval,
        )


def test_enabled_checkpointer_requires_private_signing_configuration():
    with pytest.raises(ValidationError, match="AUDIT_MERKLE_SIGNING_PRIVATE_KEY"):
        MerkleCheckpointerSettings(
            audit_merkle_checkpoint_enabled=True,
            audit_merkle_signing_key_id="",
            audit_merkle_signing_private_key="",
            audit_merkle_public_keys={},
        )


def test_development_and_hardened_compose_isolate_checkpointer_secret_file():
    root = Path(__file__).resolve().parents[3]
    for compose_name in ("docker-compose.yml", "docker-compose.hardened.yml"):
        compose = (root / compose_name).read_text(encoding="utf-8")
        before_checkpointer, checkpointer_and_after = compose.split("  merkle-checkpointer:", 1)
        checkpointer = checkpointer_and_after.split("  frontend:", 1)[0]

        assert ".env.merkle-checkpointer" not in before_checkpointer
        assert ".env.merkle-checkpointer" in checkpointer
        assert "RABBITMQ_URL" not in checkpointer
        assert "REDIS_URL" not in checkpointer
        assert "networks: [checkpoint_db]" in checkpointer


def test_public_private_signing_key_mismatch_fails_at_configuration_time():
    private_key, _ = generate_ed25519_keypair()
    _, wrong_public_key = generate_ed25519_keypair()

    with pytest.raises(ValidationError, match="does not match") as error:
        MerkleCheckpointerSettings(
            audit_merkle_checkpoint_enabled=True,
            audit_merkle_signing_key_id="audit-mismatch",
            audit_merkle_signing_private_key=private_key,
            audit_merkle_public_keys={"audit-mismatch": wrong_public_key},
        )
    assert private_key not in str(error.value)


@pytest.mark.asyncio
async def test_transient_cycle_failure_does_not_terminate_periodic_loop(signing_values):
    settings = _settings(signing_values)
    stop_event = asyncio.Event()
    calls = 0
    waits = 0

    async def runner(_session_factory, _settings):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary database outage")
        stop_event.set()
        return CheckpointCycleResult()

    async def no_delay(_stop_event, interval_seconds):
        nonlocal waits
        waits += 1
        assert interval_seconds == 60

    await run_periodic_checkpointer(
        settings,
        object(),
        stop_event=stop_event,
        cycle_runner=runner,
        interval_waiter=no_delay,
    )

    assert calls == 2
    assert waits == 1


@pytest.mark.asyncio
async def test_graceful_shutdown_interrupts_the_interval_wait(signing_values):
    settings = _settings(signing_values, audit_merkle_checkpoint_interval_seconds=300)
    stop_event = asyncio.Event()
    cycle_completed = asyncio.Event()

    async def runner(_session_factory, _settings):
        cycle_completed.set()
        return CheckpointCycleResult()

    task = asyncio.create_task(
        run_periodic_checkpointer(settings, object(), stop_event=stop_event, cycle_runner=runner)
    )
    await cycle_completed.wait()
    stop_event.set()

    await asyncio.wait_for(task, timeout=1)
    assert task.done()


@pytest.mark.asyncio
async def test_manual_cli_checkpoint_all_still_uses_shared_orchestration(
    db_session, signing_values, monkeypatch, capsys
):
    await _events(db_session, 5, "manual.compatibility")
    key_id, private_key, public_keys = signing_values
    monkeypatch.setenv("AUDIT_MERKLE_SIGNING_KEY_ID", key_id)
    monkeypatch.setenv("AUDIT_MERKLE_SIGNING_PRIVATE_KEY", private_key)
    monkeypatch.setenv("AUDIT_MERKLE_PUBLIC_KEYS", __import__("json").dumps(public_keys))

    @asynccontextmanager
    async def maintenance_session():
        yield db_session

    monkeypatch.setattr(merkle_tool, "_maintenance_session", maintenance_session)
    await merkle_tool._checkpoint(SimpleNamespace(max_leaves=2, all=True))

    assert len(list((await db_session.execute(select(AuditMerkleBatch.id))).scalars())) == 3
    assert "created checkpoint #3: leaves=1" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_admin_event_projection_distinguishes_pending_and_checkpointed_rows(db_session, signing_values):
    events = await _events(db_session, 2, "automatic.admin-state")
    event_ids = {event.id for event in events}

    pending, _ = await AdminService.list_events(
        db_session,
        q="automatic.admin-state",
        event_type=None,
        category=None,
        channel_id=None,
        actor_user_id=None,
        offset=0,
        limit=10,
    )
    await run_checkpoint_cycle(_ExistingSessionFactory(db_session), _settings(signing_values))
    checkpointed, _ = await AdminService.list_events(
        db_session,
        q="automatic.admin-state",
        event_type=None,
        category=None,
        channel_id=None,
        actor_user_id=None,
        offset=0,
        limit=10,
    )

    assert {item.id for item in pending} == event_ids
    assert all(item.event_hash and not item.merkle_checkpointed for item in pending)
    assert all(item.merkle_checkpointed for item in checkpointed)
