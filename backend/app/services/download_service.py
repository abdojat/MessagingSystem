"""Bounded protected-file streaming primitives."""

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

from starlette.responses import FileResponse


class DownloadLease:
    def __init__(self, limiter: "DownloadConcurrencyLimiter", user_id: UUID) -> None:
        self._limiter = limiter
        self._user_id = user_id
        self._released = False
        self._release_lock = asyncio.Lock()

    async def release(self) -> None:
        async with self._release_lock:
            if self._released:
                return
            self._released = True
            await self._limiter._release(self._user_id)


class DownloadConcurrencyLimiter:
    """Race-safe per-process/per-user protected-download admission."""

    def __init__(self) -> None:
        self._active: dict[UUID, int] = {}
        self._lock = asyncio.Lock()

    async def try_acquire(self, user_id: UUID, limit: int) -> DownloadLease | None:
        async with self._lock:
            current = self._active.get(user_id, 0)
            if current >= max(1, int(limit)):
                return None
            self._active[user_id] = current + 1
        return DownloadLease(self, user_id)

    async def _release(self, user_id: UUID) -> None:
        async with self._lock:
            current = self._active.get(user_id, 0)
            if current <= 1:
                self._active.pop(user_id, None)
            else:
                self._active[user_id] = current - 1

    async def active_for(self, user_id: UUID) -> int:
        async with self._lock:
            return self._active.get(user_id, 0)

    def reset_for_tests(self) -> None:
        # Test fixtures call this only when no response task is active.
        self._active.clear()


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


protected_download_limiter = DownloadConcurrencyLimiter()
