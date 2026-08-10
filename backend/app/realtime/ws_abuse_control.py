import math
import time
from dataclasses import dataclass
from typing import Callable


# Costs reflect backend work rather than wire-message count. History-producing
# commands also consume the separate row budget before any database query.
COMMAND_COSTS: dict[str, int] = {
    "ping": 1,
    "auth": 1,
    "sync": 1,
    "invalid": 1,
    "unsupported": 1,
    "seen": 3,
    "unsubscribe": 3,
    "subscribe": 10,
    "resume": 10,
}


@dataclass
class _TokenBucket:
    capacity: float
    refill_per_second: float
    clock: Callable[[], float]

    def __post_init__(self) -> None:
        self.tokens = self.capacity
        self.updated_at = self.clock()

    def consume(self, cost: float) -> int | None:
        now = self.clock()
        elapsed = max(0.0, now - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.updated_at = now
        if self.tokens >= cost:
            self.tokens -= cost
            return None
        missing = cost - self.tokens
        return max(1, math.ceil(missing / self.refill_per_second))


class WebSocketWorkBudget:
    """Per-socket weighted command and history-row token buckets.

    State cardinality is tied to admitted sockets rather than attacker-provided
    command keys. Connection and ticket quotas bound how quickly a client can
    replace a depleted per-socket budget.
    """

    def __init__(
        self,
        *,
        command_capacity: int,
        command_refill_per_second: float,
        history_capacity: int,
        history_refill_per_second: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._commands = _TokenBucket(
            float(command_capacity),
            float(command_refill_per_second),
            clock,
        )
        self._history = _TokenBucket(
            float(history_capacity),
            float(history_refill_per_second),
            clock,
        )

    def charge_command(self, command_type: str) -> int | None:
        return self._commands.consume(COMMAND_COSTS.get(command_type, COMMAND_COSTS["unsupported"]))

    def reserve_history_rows(self, maximum_rows: int) -> int | None:
        if maximum_rows <= 0:
            return None
        return self._history.consume(float(maximum_rows))
