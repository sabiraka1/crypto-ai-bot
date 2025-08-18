# src/crypto_ai_bot/utils/rate_limit.py
from __future__ import annotations
import threading
import time
from typing import Dict


class TokenBucket:
    """Простой thread-safe токен-бакет."""
    def __init__(self, rate_per_sec: float, capacity: float | None = None):
        self.rate = float(max(0.000001, rate_per_sec))
        self.capacity = float(capacity if capacity is not None else rate_per_sec)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self._lock = threading.Lock()

    def try_acquire(self, tokens: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = max(0.0, now - self.updated)
            self.updated = now
            # пополнение
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class MultiLimiter:
    """
    Набор бакетов по именам. Пример:
      lim = MultiLimiter(global_rps=10, write_rps=5)
      lim.try_acquire("global")
    """
    def __init__(self, **rates: float):
        self._buckets: Dict[str, TokenBucket] = {}
        for name, r in rates.items():
            if not name.endswith("_rps"):
                # допустим и без _rps; нормализуем
                key = name
            else:
                key = name[:-4]
            self._buckets[key] = TokenBucket(rate_per_sec=float(r))

    def try_acquire(self, name: str = "global", tokens: float = 1.0) -> bool:
        b = self._buckets.get(name)
        if b is None:
            # если не настроен конкретный бакет — используем «global», если есть
            b = self._buckets.get("global")
            if b is None:
                return True
        return b.try_acquire(tokens)
