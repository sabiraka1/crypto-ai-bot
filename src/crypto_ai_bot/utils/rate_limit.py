from __future__ import annotations

import time
from typing import Dict, Optional


class TokenBucket:
    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = int(max(1, capacity))
        self.refill_per_sec = float(max(0.0001, refill_per_sec))
        self.tokens = float(self.capacity)
        self.updated = time.monotonic()

    def try_acquire(self, n: int = 1) -> bool:
        now = time.monotonic()
        dt = now - self.updated
        self.updated = now
        self.tokens = min(self.capacity, self.tokens + dt * self.refill_per_sec)
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


class MultiLimiter:
    """
    Простой глобальный лимитер (суммарный).
    """
    def __init__(self, global_rps: float = 10.0) -> None:
        self.bucket = TokenBucket(capacity=int(max(1, global_rps * 2.0)), refill_per_sec=float(global_rps))

    def try_acquire(self, _key: str = "global", tokens: int = 1) -> bool:
        return self.bucket.try_acquire(tokens)


class GateIOLimiter:
    """
    Per-endpoint buckets: 'orders', 'market_data', 'account'.
    Значения по умолчанию — консервативные; переопределяются через Settings.
    """
    def __init__(
        self,
        *,
        orders_capacity: int = 100,
        orders_window_sec: float = 10.0,
        market_capacity: int = 600,
        market_window_sec: float = 10.0,
        account_capacity: int = 300,
        account_window_sec: float = 10.0,
    ) -> None:
        self.buckets: Dict[str, TokenBucket] = {
            "orders": TokenBucket(orders_capacity, orders_capacity / max(0.001, orders_window_sec)),
            "market_data": TokenBucket(market_capacity, market_capacity / max(0.001, market_window_sec)),
            "account": TokenBucket(account_capacity, account_capacity / max(0.001, account_window_sec)),
        }

    def try_acquire(self, endpoint_type: str, tokens: int = 1) -> bool:
        b = self.buckets.get(endpoint_type) or self.buckets["orders"]
        return b.try_acquire(tokens)
