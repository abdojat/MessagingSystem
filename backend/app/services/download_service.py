"""Bounded protected-file streaming primitives."""

import asyncio
import logging
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from starlette.responses import FileResponse, StreamingResponse

from app.core.upload_encryption import UploadEncryptionError, iter_decrypted_upload_async

logger = logging.getLogger(__name__)


class DownloadLease:
    def __init__(self, limiter: "DownloadConcurrencyLimiter", user_id: UUID, client_ip: str) -> None:
        self._limiter = limiter
        self._user_id = user_id
        self._client_ip = client_ip
        self._released = False
        self._release_lock = asyncio.Lock()

    async def release(self) -> None:
        async with self._release_lock:
            if self._released:
                return
            self._released = True
            await self._limiter._release(self._user_id, self._client_ip)


class DownloadConcurrencyLimiter:
    """Atomic user/IP/process protected-download admission in one backend."""

    def __init__(self) -> None:
        self._active_by_user: dict[UUID, int] = {}
        self._active_by_ip: dict[str, int] = {}
        self._active_global = 0
        self._lock = asyncio.Lock()

    async def try_acquire(
        self,
        user_id: UUID,
        client_ip: str,
        *,
        per_user_limit: int,
        per_ip_limit: int,
        global_limit: int,
    ) -> DownloadLease | None:
        normalized_ip = str(client_ip)[:64] or "unknown"
        user_limit = max(1, int(per_user_limit))
        ip_limit = max(1, int(per_ip_limit))
        process_limit = max(1, int(global_limit))
        async with self._lock:
            user_active = self._active_by_user.get(user_id, 0)
            ip_active = self._active_by_ip.get(normalized_ip, 0)
            # One critical section checks and increments all dimensions. Failed
            # admission changes none of them, so partial slot leaks are impossible.
            if (
                user_active >= user_limit
                or ip_active >= ip_limit
                or self._active_global >= process_limit
            ):
                return None
            self._active_by_user[user_id] = user_active + 1
            self._active_by_ip[normalized_ip] = ip_active + 1
            self._active_global += 1
        return DownloadLease(self, user_id, normalized_ip)

    async def _release(self, user_id: UUID, client_ip: str) -> None:
        async with self._lock:
            user_active = self._active_by_user.get(user_id, 0)
            if user_active <= 1:
                self._active_by_user.pop(user_id, None)
            else:
                self._active_by_user[user_id] = user_active - 1

            ip_active = self._active_by_ip.get(client_ip, 0)
            if ip_active <= 1:
                self._active_by_ip.pop(client_ip, None)
            else:
                self._active_by_ip[client_ip] = ip_active - 1

            if self._active_global > 0:
                self._active_global -= 1

    async def active_for(self, user_id: UUID) -> int:
        async with self._lock:
            return self._active_by_user.get(user_id, 0)

    async def active_for_ip(self, client_ip: str) -> int:
        async with self._lock:
            return self._active_by_ip.get(str(client_ip)[:64] or "unknown", 0)

    async def active_global(self) -> int:
        async with self._lock:
            return self._active_global

    async def state_sizes(self) -> tuple[int, int]:
        async with self._lock:
            return len(self._active_by_user), len(self._active_by_ip)

    def reset_for_tests(self) -> None:
        # Test fixtures call this only when no response task is active.
        self._active_by_user.clear()
        self._active_by_ip.clear()
        self._active_global = 0


class LeasedFileResponse(FileResponse):
    """Release admission state on completion, cancellation, or send failure."""

    def __init__(self, path: str | Path, lease: DownloadLease, **kwargs: Any) -> None:
        super().__init__(path=path, **kwargs)
        self._download_lease = lease

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._download_lease.release()


class LeasedEncryptedFileResponse(StreamingResponse):
    """Authenticated plaintext stream backed only by encrypted file bytes."""

    def __init__(
        self,
        path: str | Path,
        lease: DownloadLease,
        *,
        upload_id: UUID,
        key_id: str | None,
        plaintext_size: int,
        media_type: str,
        on_integrity_failure: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._encrypted_path = Path(path)
        self._download_lease = lease
        self._upload_id = upload_id
        self._key_id = key_id
        self._plaintext_size = int(plaintext_size)
        self._on_integrity_failure = on_integrity_failure
        super().__init__(
            self._body_iterator(),
            media_type=media_type,
            headers={
                "Content-Length": str(self._plaintext_size),
                "Cache-Control": "private, no-store",
                "Accept-Ranges": "none",
            },
        )

    async def _body_iterator(self):
        try:
            async for chunk in iter_decrypted_upload_async(
                self._encrypted_path,
                expected_upload_id=self._upload_id,
                expected_key_id=self._key_id,
                expected_plaintext_size=self._plaintext_size,
            ):
                yield chunk
        except (UploadEncryptionError, OSError):
            logger.warning("protected upload integrity failure upload_id=%s", self._upload_id)
            if self._on_integrity_failure is not None:
                try:
                    await self._on_integrity_failure("storage_integrity_failure")
                except Exception:
                    logger.warning("failed to persist upload integrity event upload_id=%s", self._upload_id)
            # Headers may already have been sent. Abort the transfer with a
            # bounded application exception and never expose crypto details.
            raise RuntimeError("protected upload transfer failed integrity validation") from None

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._download_lease.release()


protected_download_limiter = DownloadConcurrencyLimiter()
