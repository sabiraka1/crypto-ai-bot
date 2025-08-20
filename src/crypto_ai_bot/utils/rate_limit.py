# src/crypto_ai_bot/utils/rate_limit.py
from __future__ import annotations

"""
Единая реализация токен-бакета для всего проекта.
Используется и в брокере (пер-эндпоинт лимиты), и в ASGI-middleware.

Пример:
    limiter = GateIOLimiter()
    if not limiter.try_acquire("orders"):
        raise RateLimitExceeded("orders throttled")
"""

import time
import threading
from typing import Dict


class TokenBucket:
    """
    Простой thread-safe токен-бакет: capacity, refill_rate_per_sec.
    """

    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = max(1, int(capacity))
        self.refill_per_sec = float(refill_per_sec)
        self.tokens = float(self.capacity)
        self._lock = threading.Lock()
        self._last = time.monotonic()

    def try_acquire(self, amount: int = 1) -> bool:
        now = time.monotonic()
        with self._lock:
            elapsed = max(0.0, now - self._last)
            self._last = now
            # пополняем
            if self.refill_per_sec > 0:
                self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
            if self.tokens >= amount:
                self.tokens -= amount
                return True
            return False


class MultiLimiter:
    """
    Набор именованных бакетов. По умолчанию используем "default".
    """

    def __init__(self, buckets: Dict[str, TokenBucket]) -> None:
        self._buckets = dict(buckets)

    def try_acquire(self, which: str = "default", amount: int = 1) -> bool:
        bucket = self._buckets.get(which) or self._buckets.get("default")
        if not bucket:
            return True  # если не настроен — пропускаем
        return bucket.try_acquire(amount)


class GateIOLimiter(MultiLimiter):
    """
    Эмпирические лимиты (примерные), скорректируйте под ваш кейс/план.
      - orders: 100 вызовов / 10 сек (~10 rps)
      - market_data: 600 / 10 сек (~60 rps)
      - account: 300 / 10 сек (~30 rps)
    """

    def __init__(self) -> None:
        super().__init__(
            buckets={
                "default": TokenBucket(capacity=100, refill_per_sec=10.0),
                "orders": TokenBucket(capacity=100, refill_per_sec=10.0),
                "market_data": TokenBucket(capacity=600, refill_per_sec=60.0),
                "account": TokenBucket(capacity=300, refill_per_sec=30.0),
            }
        )
