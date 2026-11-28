"""Token-bucket rate limiting, in process and dependency free.

Each key (a client address) owns a bucket that holds up to ``burst`` tokens and refills at ``per_minute / 60``
tokens per second. A request spends one token; with none left it is refused and told when to retry.
Memory is bounded: idle full buckets are swept, and past ``max_keys`` the least recently seen keys go first.
This protects one process. Behind several instances, put a shared limiter (proxy / gateway) in front as well.
"""
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Tuple


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int            # bucket capacity, for X-RateLimit-Limit
    remaining: int        # whole tokens left after this request
    retry_after: int      # seconds until a token is available (0 when allowed)


class RateLimiter:
    def __init__(self, per_minute: float, burst: int, clock: Callable[[], float] = time.monotonic,
                 max_keys: int = 10_000):
        self.rate = max(0.0, per_minute) / 60.0
        self.burst = max(1, int(burst))
        self.enabled = self.rate > 0
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: Dict[str, Tuple[float, float]] = {}      # key -> (tokens, last seen)
        self._lock = threading.Lock()

    def _refill(self, key: str, now: float) -> float:
        tokens, seen = self._buckets.get(key, (float(self.burst), now))
        return min(float(self.burst), tokens + (now - seen) * self.rate)

    def check(self, key: str, cost: float = 1.0) -> Decision:
        """Spend ``cost`` tokens for ``key`` if available."""
        if not self.enabled:
            return Decision(True, self.burst, self.burst, 0)
        with self._lock:
            now = self._clock()
            tokens = self._refill(key, now)
            if tokens >= cost:
                tokens -= cost
                self._buckets[key] = (tokens, now)
                self._trim(now)
                return Decision(True, self.burst, int(tokens), 0)
            self._buckets[key] = (tokens, now)
            wait = math.ceil((cost - tokens) / self.rate)
            return Decision(False, self.burst, 0, max(1, wait))

    def blocked(self, key: str) -> Decision:
        """Look at ``key`` without spending a token (used to lock out repeated auth failures)."""
        if not self.enabled:
            return Decision(True, self.burst, self.burst, 0)
        with self._lock:
            tokens = self._refill(key, self._clock())
            if tokens >= 1.0:
                return Decision(True, self.burst, int(tokens), 0)
            return Decision(False, self.burst, 0, max(1, math.ceil((1.0 - tokens) / self.rate)))

    def _trim(self, now: float) -> None:
        if len(self._buckets) <= self._max_keys:
            return
        full_after = self.burst / self.rate if self.rate else 0.0
        stale = [k for k, (_, seen) in self._buckets.items() if now - seen >= full_after]
        for k in stale:                                  # a bucket idle long enough is full again: forget it
            del self._buckets[k]
        if len(self._buckets) > self._max_keys:           # still too many: drop the least recently seen
            oldest = sorted(self._buckets, key=lambda k: self._buckets[k][1])
            for k in oldest[: len(self._buckets) - self._max_keys]:
                del self._buckets[k]

    def __len__(self) -> int:
        return len(self._buckets)
