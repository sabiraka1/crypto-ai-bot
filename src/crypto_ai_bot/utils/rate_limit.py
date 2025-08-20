# src/crypto_ai_bot/utils/rate_limit.py
from __future__ import annotations
import time
import threading

class TokenBucket:
    def __init__(self, capacity: int, refill_per_sec: float):
        self.capacity = max(1, capacity)
        self.refill_per_sec = max(0.0, refill_per_sec)
        self.tokens = float(capacity)
        self.updated = time.monotonic()
        self._lock = threading.Lock()

    def try_acquire(self, n: int = 1) -> bool:
        now = time.monotonic()
        with self._lock:
            elapsed = now - self.updated
            if elapsed > 0:
                self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
                self.updated = now
            if self.tokens >= n:
                self.tokens -= n
                return True
            return False

class MultiLimiter:
    """Backward-compatible global limiter used elsewhere in the code."""
    def __init__(self, global_rps: float = 10.0):
        cap = max(1, int(global_rps * 2))
        self.bucket = TokenBucket(capacity=cap, refill_per_sec=global_rps)

    def try_acquire(self, tokens: int = 1) -> bool:
        return self.bucket.try_acquire(tokens)

class GateIOLimiter:
    """Per-endpoint buckets for Gate.io. Endpoints: orders / market_data / account."""
    def __init__(
        self,
        orders_capacity: int = 100, orders_window_sec: float = 10.0,
        market_capacity: int = 600, market_window_sec: float = 10.0,
        account_capacity: int = 300, account_window_sec: float = 10.0,
    ):
        self.buckets = {
            "orders": TokenBucket(orders_capacity, orders_capacity / orders_window_sec),
            "market_data": TokenBucket(market_capacity, market_capacity / market_window_sec),
            "account": TokenBucket(account_capacity, account_capacity / account_window_sec),
        }

    def try_acquire(self, endpoint: str, tokens: int = 1) -> bool:
        bucket = self.buckets.get(endpoint)
        if bucket is None:
            # default to orders if unknown
            bucket = self.buckets["orders"]
        return bucket.try_acquire(tokens)
