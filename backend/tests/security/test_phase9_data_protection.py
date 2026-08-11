import base64
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from starlette.requests import Request

from app.api.routes.messages import get_upload_content
from app.core.config import DEVELOPMENT_DATA_KEY_ID, MAX_DATA_ENCRYPTION_KEYS, Settings, get_settings
from app.core import encryption
from app.core.encryption import (
    decrypt_json_payload,
    decrypt_message,
    encrypt_json_payload,
    encrypt_message,
    encrypt_message_with_key,
)
from app.core.errors import AppError
from app.core.upload_encryption import (
    UPLOAD_ENCRYPTION_MAGIC,
    UploadEncryptionError,
    encrypt_plaintext_file,
    iter_decrypted_upload_async,
    read_upload_encryption_header_from_path,
    reencrypt_upload_file,
    validate_encrypted_upload_file,
)
from app.db.crypto_tool import collect_status, migrate_messages, migrate_uploads
from app.db.models import (
    Channel,
    ChannelJoinMode,
    ChannelMembership,
    ChannelVisibility,
    ContentType,
    Event,
    MembershipRole,
    Message,
    Outbox,
    Upload,
    User,
)
from app.schemas.messages import PublishMessageRequest, UploadCreateRequest
from app.services.download_service import DownloadConcurrencyLimiter, LeasedEncryptedFileResponse
from app.services.message_service import MessageService


KEY_A = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
KEY_B = base64.urlsafe_b64encode(bytes(range(32, 64))).decode("ascii")
LEGACY_KEY = base64.urlsafe_b64encode(b"legacy-phase9-fernet-key-32byt!!").decode("ascii")
SECURE_JWT = "phase9-secure-jwt-secret-with-sufficient-diversity-0123456789"


def _clear_crypto_caches() -> None:
    get_settings.cache_clear()
    encryption._build_key_ring.cache_clear()
    encryption._build_fernet.cache_clear()
    encryption._build_legacy_fernet.cache_clear()


def _configure_ring(
    monkeypatch: pytest.MonkeyPatch,
    *,
    active: str = "key-b",
    keys: dict[str, str] | None = None,
    allow_plaintext_messages: bool = False,
    allow_plaintext_uploads: bool = False,
    uploads_base_dir: Path | None = None,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATA_ENCRYPTION_ACTIVE_KEY_ID", active)
    monkeypatch.setenv("DATA_ENCRYPTION_KEYS", json.dumps(keys or {"key-a": KEY_A, "key-b": KEY_B}))
    monkeypatch.setenv("MESSAGE_ENCRYPTION_KEY", LEGACY_KEY)
    monkeypatch.setenv("ALLOW_LEGACY_PLAINTEXT_MESSAGES", str(allow_plaintext_messages).lower())
    monkeypatch.setenv("ALLOW_LEGACY_PLAINTEXT_UPLOADS", str(allow_plaintext_uploads).lower())
    if uploads_base_dir is not None:
        monkeypatch.setenv("UPLOADS_BASE_DIR", str(uploads_base_dir))
    _clear_crypto_caches()


def _production_settings(**overrides):
    values = {
        "_env_file": None,
        "environment": "production",
        "jwt_secret": SECURE_JWT,
        "cors_origins": ["https://chat.example.com"],
        "trusted_hosts": ["chat.example.com"],
        "data_encryption_active_key_id": "key-a",
        "data_encryption_keys": {"key-a": KEY_A},
        "message_encryption_key": "",
        "allow_legacy_plaintext_messages": False,
        "allow_legacy_plaintext_uploads": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_key_ring_production_requirements_and_active_key_membership() -> None:
    with pytest.raises(ValidationError, match="DATA_ENCRYPTION_KEYS"):
        _production_settings(data_encryption_active_key_id="", data_encryption_keys="")
    with pytest.raises(ValidationError, match="must reference"):
        _production_settings(data_encryption_active_key_id="missing")
    settings = _production_settings()
    assert settings.data_encryption_active_key_id == "key-a"
    assert set(settings.data_encryption_keys) == {"key-a"}


@pytest.mark.parametrize(
    ("active", "keys"),
    [
        ("key-a", "not-json"),
        ("key-a", {"key-a": "%%%"}),
        ("key-a", {"key-a": base64.urlsafe_b64encode(b"short").decode("ascii")}),
        ("bad/key", {"bad/key": KEY_A}),
        ("key-a", {f"key-{index}": KEY_A for index in range(MAX_DATA_ENCRYPTION_KEYS + 1)}),
        ("key-a", '{"key-a":"%s","key-a":"%s"}' % (KEY_A, KEY_B)),
    ],
)
def test_key_ring_rejects_malformed_bounded_or_duplicate_configuration(active, keys) -> None:
    with pytest.raises(ValidationError):
        _production_settings(data_encryption_active_key_id=active, data_encryption_keys=keys)


def test_key_validation_errors_hide_secret_values() -> None:
    secret_marker = "do-not-echo-this-key-material"
    with pytest.raises(ValidationError) as captured:
        _production_settings(data_encryption_keys={"key-a": secret_marker})
    assert secret_marker not in str(captured.value)


def test_development_fallback_is_explicitly_environment_bounded() -> None:
    dev = Settings(
        _env_file=None,
        environment="development",
        data_encryption_active_key_id="",
        data_encryption_keys="",
    )
    assert dev.data_encryption_active_key_id == DEVELOPMENT_DATA_KEY_ID
    with pytest.raises(ValidationError):
        _production_settings(data_encryption_active_key_id="", data_encryption_keys="")
    with pytest.raises(ValidationError, match="cannot be enabled"):
        _production_settings(allow_legacy_plaintext_messages=True)
    with pytest.raises(ValidationError, match="cannot be enabled"):
        _production_settings(allow_legacy_plaintext_uploads=True)


def test_message_v2_text_and_json_round_trip_without_plaintext(monkeypatch) -> None:
    _configure_ring(monkeypatch)
    text = encrypt_message("phase9-secret-text")
    structured = encrypt_json_payload({"marker": "phase9-secret-json", "nested": {"ok": True}})
    assert text.startswith("enc:v2:key-b:")
    assert "phase9-secret-text" not in text
    assert structured.keys() == {"_enc_v2"}
    assert structured["_enc_v2"].keys() == {"kid", "token"}
    assert structured["_enc_v2"]["kid"] == "key-b"
    assert "phase9-secret-json" not in json.dumps(structured)
    assert decrypt_message(text) == "phase9-secret-text"
    assert decrypt_json_payload(structured) == {"marker": "phase9-secret-json", "nested": {"ok": True}}


def test_message_rotation_keeps_old_key_readable_and_new_writes_switch(monkeypatch) -> None:
    _configure_ring(monkeypatch, active="key-a")
    old_ciphertext = encrypt_message("old-message")
    assert old_ciphertext.startswith("enc:v2:key-a:")
    _configure_ring(monkeypatch, active="key-b")
    new_ciphertext = encrypt_message("new-message")
    assert new_ciphertext.startswith("enc:v2:key-b:")
    assert decrypt_message(old_ciphertext) == "old-message"
    assert decrypt_message(new_ciphertext) == "new-message"


def test_message_unknown_key_tamper_and_plaintext_fail_closed(monkeypatch) -> None:
    _configure_ring(monkeypatch)
    ciphertext = encrypt_message("authenticated-message")
    unknown = ciphertext.replace("enc:v2:key-b:", "enc:v2:missing:", 1)
    with pytest.raises(AppError) as missing:
        decrypt_message(unknown)
    assert missing.value.code == "DECRYPTION_FAILED"
    tampered = ciphertext[:-2] + ("A" if ciphertext[-2] != "A" else "B") + ciphertext[-1]
    with pytest.raises(AppError):
        decrypt_message(tampered)
    with pytest.raises(AppError):
        decrypt_message("historical plaintext")
    with pytest.raises(AppError):
        decrypt_json_payload({"_enc_v2": {"kid": "key-b", "token": "bad"}, "extra": True})


def test_legacy_v1_and_plaintext_require_explicit_compatibility(monkeypatch) -> None:
    legacy_token = Fernet(LEGACY_KEY.encode("ascii")).encrypt(b"legacy-v1").decode("ascii")
    _configure_ring(monkeypatch, allow_plaintext_messages=False)
    assert decrypt_message(legacy_token) == "legacy-v1"
    with pytest.raises(AppError):
        decrypt_message("legacy plaintext")
    _configure_ring(monkeypatch, allow_plaintext_messages=True)
    assert decrypt_message("legacy plaintext") == "legacy plaintext"
    assert decrypt_json_payload({"legacy": "json"}) == {"legacy": "json"}


def _make_encrypted_upload(path: Path, payload: bytes, upload_id, key_id: str) -> None:
    plaintext = path.with_suffix(".plain")
    plaintext.write_bytes(payload)
    encrypt_plaintext_file(
        plaintext,
        path,
        upload_id=upload_id,
        key_id=key_id,
        plaintext_size=len(payload),
        expected_checksum=hashlib.sha256(payload).hexdigest(),
    )
    plaintext.unlink()


@pytest.mark.asyncio
async def test_upload_encrypted_format_hides_marker_and_streams_exact_plaintext(monkeypatch, tmp_path) -> None:
    _configure_ring(monkeypatch)
    payload = (b"secret-marker-123:" + bytes(range(251))) * 12_000
    upload_id = uuid4()
    encrypted = tmp_path / "encrypted.bin"
    _make_encrypted_upload(encrypted, payload, upload_id, "key-b")
    stored = encrypted.read_bytes()
    assert stored.startswith(UPLOAD_ENCRYPTION_MAGIC)
    assert b"secret-marker-123" not in stored
    header, checksum = validate_encrypted_upload_file(
        encrypted,
        expected_upload_id=upload_id,
        expected_plaintext_size=len(payload),
        expected_checksum=hashlib.sha256(payload).hexdigest(),
    )
    assert header.plaintext_size == len(payload)
    assert checksum == hashlib.sha256(payload).hexdigest()
    downloaded = bytearray()
    async for chunk in iter_decrypted_upload_async(
        encrypted,
        expected_upload_id=upload_id,
        expected_key_id="key-b",
        expected_plaintext_size=len(payload),
    ):
        assert len(chunk) <= 64 * 1024
        downloaded.extend(chunk)
    assert bytes(downloaded) == payload


@pytest.mark.parametrize(
    "mutation",
    [
        "magic",
        "version",
        "key_id",
        "plaintext_size",
        "chunk_size",
        "nonce",
        "header_tag",
        "frame_index",
        "frame_length",
        "ciphertext",
        "gcm_tag",
        "truncate",
        "trailing",
    ],
)
def test_upload_corruption_and_header_bombs_fail_safely(monkeypatch, tmp_path, mutation) -> None:
    _configure_ring(monkeypatch)
    payload = b"x" * (70 * 1024)
    upload_id = uuid4()
    encrypted = tmp_path / f"{mutation}.bin"
    _make_encrypted_upload(encrypted, payload, upload_id, "key-b")
    data = bytearray(encrypted.read_bytes())
    key_len = data[25]
    size_offset = 26 + key_len
    nonce_offset = size_offset + 12
    header_tag_offset = nonce_offset + 8
    frame_offset = header_tag_offset + 16
    positions = {
        "magic": 0,
        "version": 8,
        "key_id": 26,
        "plaintext_size": size_offset,
        "chunk_size": size_offset + 8,
        "nonce": nonce_offset,
        "header_tag": header_tag_offset,
        "frame_index": frame_offset + 3,
        "frame_length": frame_offset + 7,
        "ciphertext": frame_offset + 8,
        "gcm_tag": frame_offset + 8 + 64 * 1024,
    }
    if mutation == "truncate":
        data.pop()
    elif mutation == "trailing":
        data.extend(b"unexpected")
    else:
        position = positions[mutation]
        data[position] ^= 1
    encrypted.write_bytes(data)
    with pytest.raises(UploadEncryptionError):
        validate_encrypted_upload_file(
            encrypted,
            expected_upload_id=upload_id,
            expected_plaintext_size=len(payload),
        )


def test_upload_header_key_length_bomb_is_rejected_before_large_read(monkeypatch, tmp_path) -> None:
    _configure_ring(monkeypatch)
    upload_id = uuid4()
    encrypted = tmp_path / "bomb.bin"
    _make_encrypted_upload(encrypted, b"small", upload_id, "key-b")
    data = bytearray(encrypted.read_bytes())
    data[25] = 255
    encrypted.write_bytes(data)
    with pytest.raises(UploadEncryptionError):
        read_upload_encryption_header_from_path(encrypted, expected_upload_id=upload_id)


def test_upload_key_rotation_and_old_key_removal_proof(monkeypatch, tmp_path) -> None:
    _configure_ring(monkeypatch, active="key-a")
    payload = b"rotation-proof" * 20_000
    upload_id = uuid4()
    old_file = tmp_path / "old.enc"
    rotated = tmp_path / "rotated.enc"
    _make_encrypted_upload(old_file, payload, upload_id, "key-a")
    reencrypt_upload_file(
        old_file,
        rotated,
        upload_id=upload_id,
        source_key_id="key-a",
        target_key_id="key-b",
        plaintext_size=len(payload),
    )
    _configure_ring(monkeypatch, active="key-b", keys={"key-b": KEY_B})
    header, _ = validate_encrypted_upload_file(
        rotated,
        expected_upload_id=upload_id,
        expected_key_id="key-b",
        expected_plaintext_size=len(payload),
    )
    assert header.key_id == "key-b"


@pytest.mark.asyncio
async def test_encrypted_response_releases_lease_on_tamper_and_send_failure(monkeypatch, tmp_path) -> None:
    _configure_ring(monkeypatch)
    payload = b"z" * (128 * 1024)
    upload_id = uuid4()
    encrypted = tmp_path / "response.enc"
    _make_encrypted_upload(encrypted, payload, upload_id, "key-b")
    limiter = DownloadConcurrencyLimiter()
    user_id = uuid4()

    lease = await limiter.try_acquire(user_id, "127.0.0.1", per_user_limit=1, per_ip_limit=1, global_limit=1)
    assert lease is not None
    response = LeasedEncryptedFileResponse(
        encrypted,
        lease,
        upload_id=upload_id,
        key_id="key-b",
        plaintext_size=len(payload),
        media_type="application/octet-stream",
    )

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def failed_send(message):
        if message["type"] == "http.response.body":
            raise RuntimeError("simulated disconnect")

    with pytest.raises(RuntimeError, match="simulated disconnect"):
        await response(
            {"type": "http", "method": "GET", "path": "/", "headers": [], "asgi": {"spec_version": "2.4"}},
            receive,
            failed_send,
        )
    assert await limiter.active_global() == 0

    data = bytearray(encrypted.read_bytes())
    data[-1] ^= 1
    encrypted.write_bytes(data)
    lease = await limiter.try_acquire(user_id, "127.0.0.1", per_user_limit=1, per_ip_limit=1, global_limit=1)
    response = LeasedEncryptedFileResponse(
        encrypted,
        lease,
        upload_id=upload_id,
        key_id="key-b",
        plaintext_size=len(payload),
        media_type="application/octet-stream",
    )
    with pytest.raises(RuntimeError, match="integrity validation"):
        await response(
            {"type": "http", "method": "GET", "path": "/", "headers": [], "asgi": {"spec_version": "2.4"}},
            receive,
            lambda message: _async_none(),
        )
    assert await limiter.active_global() == 0


async def _async_none():
    return None


class _RateRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def ttl(self, key: str) -> int:
        return 60


def _http_scope(*, range_header: bytes | None = None) -> dict:
    headers = [] if range_header is None else [(b"range", range_header)]
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "scheme": "http",
        "method": "GET",
        "path": "/v1/uploads/content",
        "raw_path": b"/v1/uploads/content",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "extensions": {},
    }


async def _receive_request() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _create_owner_channel(db_session):
    owner = User(username=f"phase9-{uuid4().hex[:10]}", email=None, password_hash="hash")
    db_session.add(owner)
    await db_session.flush()
    channel = Channel(
        owner_user_id=owner.id,
        name="Phase 9",
        channel_slug=f"phase9-{uuid4().hex[:10]}",
        visibility=ChannelVisibility.private,
        join_mode=ChannelJoinMode.invite_only,
    )
    db_session.add(channel)
    await db_session.flush()
    db_session.add(
        ChannelMembership(
            channel_id=channel.id,
            user_id=owner.id,
            role=MembershipRole.owner,
            created_by_user_id=owner.id,
        )
    )
    await db_session.commit()
    return owner, channel


@pytest.mark.asyncio
async def test_new_message_db_and_outbox_use_v2_without_plaintext(db_session, monkeypatch) -> None:
    _configure_ring(monkeypatch)
    owner, channel = await _create_owner_channel(db_session)
    message = await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(content_text="db-plaintext-marker-phase9"),
    )
    assert message.content_text.startswith("enc:v2:key-b:")
    assert "db-plaintext-marker-phase9" not in message.content_text
    assert MessageService._decrypt_message_content(message) == ("db-plaintext-marker-phase9", None)
    outbox = (await db_session.execute(select(Outbox).where(Outbox.aggregate_id == message.id))).scalar_one()
    assert outbox.payload["content_text"] == message.content_text
    assert "db-plaintext-marker-phase9" not in json.dumps(outbox.payload)


@pytest.mark.asyncio
async def test_message_migration_rotation_is_idempotent_and_creates_no_delivery_or_audit_rows(db_session, monkeypatch) -> None:
    _configure_ring(monkeypatch, active="key-b", allow_plaintext_messages=True)
    owner, channel = await _create_owner_channel(db_session)
    legacy = Fernet(LEGACY_KEY.encode("ascii")).encrypt(b"legacy-row").decode("ascii")
    rows = [
        Message(channel_id=channel.id, sender_user_id=owner.id, seq_id=1, content_type=ContentType.text, content_text=legacy),
        Message(channel_id=channel.id, sender_user_id=owner.id, seq_id=2, content_type=ContentType.json, content_json={"plain": True}),
        Message(
            channel_id=channel.id,
            sender_user_id=owner.id,
            seq_id=3,
            content_type=ContentType.text,
            content_text=encrypt_message_with_key("old-v2", "key-a"),
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    original = {row.id: (row.seq_id, row.content_type, row.created_at) for row in rows}
    before_outbox = await db_session.scalar(select(func.count(Outbox.id)))
    before_events = await db_session.scalar(select(func.count(Event.id)))

    migrated = await migrate_messages(batch_size=1)
    assert migrated["reencrypted"] == 2
    second = await migrate_messages(batch_size=2)
    assert second["reencrypted"] == 0
    rotated = await migrate_messages(batch_size=1, target_key_id="key-b", rotate_v2=True)
    assert rotated["reencrypted"] == 1

    _configure_ring(monkeypatch, active="key-b", keys={"key-b": KEY_B}, allow_plaintext_messages=False)
    db_session.expire_all()
    current_rows = list((await db_session.execute(select(Message).order_by(Message.seq_id))).scalars().all())
    assert all(row.content_text is None or row.content_text.startswith("enc:v2:key-b:") for row in current_rows)
    assert all(row.content_json is None or row.content_json["_enc_v2"]["kid"] == "key-b" for row in current_rows)
    assert {row.id: (row.seq_id, row.content_type, row.created_at) for row in current_rows} == original
    assert [MessageService._decrypt_message_content(row) for row in current_rows] == [
        ("legacy-row", None),
        (None, {"plain": True}),
        ("old-v2", None),
    ]
    assert await db_session.scalar(select(func.count(Outbox.id))) == before_outbox
    assert await db_session.scalar(select(func.count(Event.id))) == before_events


@pytest.mark.asyncio
async def test_new_upload_store_is_encrypted_immutable_and_exact(db_session, monkeypatch, tmp_path) -> None:
    _configure_ring(monkeypatch, uploads_base_dir=tmp_path)
    owner = User(username=f"upload-{uuid4().hex[:10]}", email=None, password_hash="hash")
    db_session.add(owner)
    await db_session.commit()
    payload = b"secret-marker-123" + (b"0123456789" * 15_000)
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(
            filename="phase9.bin",
            content_type="application/pdf",
            size_bytes=len(payload),
            checksum=hashlib.sha256(payload).hexdigest(),
        ),
    )

    async def awkward_chunks():
        yield payload[:17]
        yield payload[17:80_123]
        yield payload[80_123:]

    stored = await MessageService.store_upload_content(db_session, owner.id, upload.id, awkward_chunks())
    path = MessageService._resolve_upload_path(str(tmp_path), upload.storage_path)
    raw = path.read_bytes()
    assert b"secret-marker-123" not in raw
    assert stored.storage_encryption_version == 1
    assert stored.storage_key_id == "key-b"
    assert stored.size_bytes == len(payload)
    assert stored.checksum == hashlib.sha256(payload).hexdigest()
    plaintext = bytearray()
    async for chunk in iter_decrypted_upload_async(
        path,
        expected_upload_id=upload.id,
        expected_key_id="key-b",
        expected_plaintext_size=len(payload),
    ):
        plaintext.extend(chunk)
    assert bytes(plaintext) == payload
    with pytest.raises(AppError) as immutable:
        await MessageService.store_upload_content(db_session, owner.id, upload.id, b"x" * len(payload))
    assert immutable.value.code == "UPLOAD_IMMUTABLE"
    assert path.read_bytes() == raw


@pytest.mark.asyncio
async def test_authorized_route_streams_encrypted_upload_and_rejects_ranges(db_session, monkeypatch, tmp_path) -> None:
    _configure_ring(monkeypatch, uploads_base_dir=tmp_path)
    owner = User(username=f"route-{uuid4().hex[:10]}", email=None, password_hash="hash")
    db_session.add(owner)
    await db_session.commit()
    payload = b"route-encrypted-download" * 7_000
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="route.pdf", content_type="application/pdf", size_bytes=len(payload)),
    )
    await MessageService.store_upload_content(db_session, owner.id, upload.id, payload)
    response = await get_upload_content(
        upload.id,
        Request(_http_scope()),
        db_session,
        owner,
        _RateRedis(),
    )
    assert isinstance(response, LeasedEncryptedFileResponse)
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    await response(_http_scope(), _receive_request, send)
    assert b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body") == payload

    with pytest.raises(HTTPException) as range_error:
        await get_upload_content(
            upload.id,
            Request(_http_scope(range_header=b"bytes=0-9")),
            db_session,
            owner,
            _RateRedis(),
        )
    assert range_error.value.status_code == 416


@pytest.mark.asyncio
async def test_upload_migration_crash_recovery_rotation_and_key_removal(db_session, monkeypatch, tmp_path) -> None:
    _configure_ring(monkeypatch, active="key-b", allow_plaintext_uploads=True, uploads_base_dir=tmp_path)
    owner = User(username=f"migrate-{uuid4().hex[:10]}", email=None, password_hash="hash")
    db_session.add(owner)
    await db_session.flush()
    plaintext_payload = b"plaintext-migration-marker" * 4_000
    crash_payload = b"crash-recovery-marker" * 4_000
    plaintext_upload = Upload(
        owner_user_id=owner.id,
        filename="legacy.bin",
        content_type="application/pdf",
        size_bytes=len(plaintext_payload),
        checksum=hashlib.sha256(plaintext_payload).hexdigest(),
        storage_path=f"{owner.id}/legacy.bin",
        public_url="stored",
    )
    crash_upload = Upload(
        owner_user_id=owner.id,
        filename="crash.bin",
        content_type="application/pdf",
        size_bytes=len(crash_payload),
        checksum=hashlib.sha256(crash_payload).hexdigest(),
        storage_path=f"{owner.id}/crash.bin",
        public_url="stored",
    )
    db_session.add_all([plaintext_upload, crash_upload])
    await db_session.commit()
    plaintext_upload_id = plaintext_upload.id
    crash_upload_id = crash_upload.id
    plaintext_path = MessageService._resolve_upload_path(str(tmp_path), plaintext_upload.storage_path)
    crash_path = MessageService._resolve_upload_path(str(tmp_path), crash_upload.storage_path)
    plaintext_path.parent.mkdir(parents=True, exist_ok=True)
    plaintext_path.write_bytes(plaintext_payload)
    _make_encrypted_upload(crash_path, crash_payload, crash_upload.id, "key-a")
    crash_bytes_before = crash_path.read_bytes()

    migrated = await migrate_uploads(batch_size=1)
    assert migrated["encrypted"] == 1
    assert migrated["metadata_repaired"] == 1
    assert crash_path.read_bytes() == crash_bytes_before
    second = await migrate_uploads(batch_size=2)
    assert second["unchanged"] == 2
    rotated = await migrate_uploads(batch_size=1, target_key_id="key-b", rotate_v1=True)
    assert rotated["reencrypted"] == 1

    _configure_ring(monkeypatch, active="key-b", keys={"key-b": KEY_B}, uploads_base_dir=tmp_path)
    db_session.expire_all()
    for upload, path, expected in (
        (await db_session.get(Upload, plaintext_upload_id), plaintext_path, plaintext_payload),
        (await db_session.get(Upload, crash_upload_id), crash_path, crash_payload),
    ):
        assert upload.storage_encryption_version == 1
        assert upload.storage_key_id == "key-b"
        header, _ = validate_encrypted_upload_file(
            path,
            expected_upload_id=upload.id,
            expected_key_id="key-b",
            expected_plaintext_size=len(expected),
        )
        assert header.key_id == "key-b"
    status = await collect_status(batch_size=1)
    assert status.upload_formats["encrypted-v1 key-b"] == 2
    assert status.upload_invalid == 0
    assert status.upload_metadata_mismatch == 0
