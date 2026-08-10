"""Bounded protected-file streaming primitives."""

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

from starlette.responses import FileResponse


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


protected_download_limiter = DownloadConcurrencyLimiter()
