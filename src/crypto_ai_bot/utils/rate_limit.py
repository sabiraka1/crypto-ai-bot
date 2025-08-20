# src/crypto_ai_bot/utils/rate_limit.py
from __future__ import annotations
import time
import threading
from typing import Dict

class TokenBucket:
    def __init__(self, capacity: int, refill_per_sec: float):
        self.capacity = max(1, int(capacity))
        self.refill_per_sec = float(refill_per_sec)
        self._tokens = float(self.capacity)
        self._ts = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        dt = now - self._ts
        if dt <= 0:
            return
        self._ts = now
        self._tokens = min(self.capacity, self._tokens + dt * self.refill_per_sec)

    def try_acquire(self, n: int = 1) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False

class MultiLimiter:
    """
    Named token-buckets, suitable for:
      - API endpoints ("orders", "market_data", "account")
      - ASGI ingress rate-limit
    """
    def __init__(self, buckets: Dict[str, TokenBucket], default_bucket: str | None = None):
        self.buckets = buckets
        self.default_name = default_bucket or next(iter(buckets.keys()))

    def try_acquire(self, name: str | None = None, n: int = 1) -> bool:
        b = self.buckets.get(name or self.default_name) or self.buckets[self.default_name]
        return b.try_acquire(n)
