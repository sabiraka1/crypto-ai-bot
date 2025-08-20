# src/crypto_ai_bot/utils/rate_limit.py
from __future__ import annotations
import time
from typing import Dict

class TokenBucket:
    """
    Простой токен-бакет (thread/async-safe при вызове из одного потока-лупа).
    capacity — максимальное число «токенов» в окне,
    refill_per_sec — скорость пополнения (токенов в сек).
    """
    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = float(max(1, capacity))
        self.refill_per_sec = float(max(0.001, refill_per_sec))
        self._tokens = self.capacity
        self._ts = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = max(0.0, now - self._ts)
        self._ts = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_sec)

    def try_acquire(self, tokens: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

class MultiLimiter:
    """
    Набор именованных бакетов: orders / market_data / account / inbound_http и т.п.
    """
    def __init__(self, buckets: Dict[str, TokenBucket]) -> None:
        self._buckets = buckets

    def try_acquire(self, name: str, tokens: float = 1.0) -> bool:
        b = self._buckets.get(name)
        if not b:
            # если бакета нет — не ограничиваем
            return True
        return b.try_acquire(tokens)
