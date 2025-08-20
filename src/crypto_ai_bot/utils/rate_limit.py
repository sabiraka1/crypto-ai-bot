# src/crypto_ai_bot/utils/rate_limit.py
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Dict, Optional

class TokenBucket:
    """Простой token-bucket: capacity токенов, пополнение refill_per_sec."""
    __slots__ = ("capacity", "refill_per_sec", "_tokens", "_last")

    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = max(1, int(capacity))
        self.refill_per_sec = float(refill_per_sec)
        self._tokens = float(self.capacity)
        self._last = monotonic()

    def _refill(self) -> None:
        now = monotonic()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_sec)
            self._last = now

    def try_acquire(self, n: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False

    def acquire_blocking(self, n: float = 1.0, timeout_sec: float = 0.0, sleep_step: float = 0.05) -> bool:
        deadline = monotonic() + timeout_sec if timeout_sec > 0 else None
        while True:
            if self.try_acquire(n):
                return True
            if deadline is not None and monotonic() >= deadline:
                return False
            sleep(sleep_step)


@dataclass
class MultiLimiter:
    """Набор бакетов по ключам (например, orders/market_data/account)."""
    buckets: Dict[str, TokenBucket]
    fallback_key: str = "default"

    def try_acquire(self, key: str, n: float = 1.0) -> bool:
        b = self.buckets.get(key) or self.buckets.get(self.fallback_key)
        return b.try_acquire(n) if b else True

    def acquire_blocking(self, key: str, n: float = 1.0, timeout_sec: float = 0.0) -> bool:
        b = self.buckets.get(key) or self.buckets.get(self.fallback_key)
        return b.acquire_blocking(n, timeout_sec) if b else True


def build_gateio_limiter_from_settings(settings) -> MultiLimiter:
    """
    Собирает MultiLimiter по эндпоинтам с дефолтами, которые можно переопределить через Settings.
      ORDERS_CAPACITY / ORDERS_WINDOW_SEC
      MARKET_CAPACITY / MARKET_WINDOW_SEC
      ACCOUNT_CAPACITY / ACCOUNT_WINDOW_SEC
      DEFAULT_CAPACITY / DEFAULT_WINDOW_SEC
    """
    def _tb(cap: int, window_sec: float) -> TokenBucket:
        # refill_per_sec = capacity / window
        refill = cap / max(0.001, window_sec)
        return TokenBucket(capacity=cap, refill_per_sec=refill)

    orders_cap = int(getattr(settings, "ORDERS_CAPACITY", 100))
    orders_win = float(getattr(settings, "ORDERS_WINDOW_SEC", 10.0))

    market_cap = int(getattr(settings, "MARKET_CAPACITY", 600))
    market_win = float(getattr(settings, "MARKET_WINDOW_SEC", 10.0))

    account_cap = int(getattr(settings, "ACCOUNT_CAPACITY", 300))
    account_win = float(getattr(settings, "ACCOUNT_WINDOW_SEC", 10.0))

    default_cap = int(getattr(settings, "DEFAULT_CAPACITY", 300))
    default_win = float(getattr(settings, "DEFAULT_WINDOW_SEC", 10.0))

    return MultiLimiter(
        buckets={
            "orders": _tb(orders_cap, orders_win),
            "market_data": _tb(market_cap, market_win),
            "account": _tb(account_cap, account_win),
            "default": _tb(default_cap, default_win),
        },
        fallback_key="default",
    )
