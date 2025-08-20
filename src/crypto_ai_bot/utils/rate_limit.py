# src/crypto_ai_bot/utils/rate_limit.py
from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Dict, Optional


class TokenBucket:
    """
    Простой thread-safe токен-бакет.
    - capacity: максимальное число токенов в бакете
    - refill_per_sec: скорость пополнения токенов в сек (tokens/sec)
    """
    __slots__ = ("capacity", "refill_per_sec", "_tokens", "_ts", "_lock")

    def __init__(self, capacity: int, window_sec: float):
        if capacity <= 0 or window_sec <= 0:
            raise ValueError("TokenBucket: capacity and window_sec must be positive")
        self.capacity = float(capacity)
        self.refill_per_sec = self.capacity / float(window_sec)
        self._tokens = self.capacity
        self._ts = time.monotonic()
        self._lock = threading.Lock()

    def try_acquire(self, tokens: float = 1.0) -> bool:
        now = time.monotonic()
        with self._lock:
            # пополнить
            elapsed = now - self._ts
            if elapsed > 0:
                self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_sec)
                self._ts = now
            # списать
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False


@dataclass(frozen=True)
class _LimiterCfg:
    capacity: int
    window_sec: float


class MultiLimiter:
    """
    Набор именованных бакетов (например: orders / market_data / account / http).
    """
    def __init__(self, buckets: Dict[str, TokenBucket]):
        self._buckets = dict(buckets)

    def try_acquire(self, bucket: str, tokens: float = 1.0) -> bool:
        b = self._buckets.get(bucket)
        if b is None:
            # если бакет не определён — разрешаем (не блокируем неожиданно прод)
            return True
        return b.try_acquire(tokens)


class GateIOLimiter(MultiLimiter):
    """
    Per-endpoint limiter для Gate.io.
    По умолчанию (согласно документации Gate) ставим консервативные лимиты,
    но позволяем переопределить из Settings.
    """
    def __init__(self, settings: Optional[object] = None):
        # defaults (tokens per WINDOW)
        orders = _LimiterCfg(capacity=100, window_sec=10.0)
        market = _LimiterCfg(capacity=600, window_sec=10.0)
        account = _LimiterCfg(capacity=300, window_sec=10.0)

        if settings is not None:
            orders = _LimiterCfg(
                capacity=int(getattr(settings, "RL_ORDERS_CAP", orders.capacity)),
                window_sec=float(getattr(settings, "RL_ORDERS_WINDOW_SEC", orders.window_sec)),
            )
            market = _LimiterCfg(
                capacity=int(getattr(settings, "RL_MARKET_DATA_CAP", market.capacity)),
                window_sec=float(getattr(settings, "RL_MARKET_DATA_WINDOW_SEC", market.window_sec)),
            )
            account = _LimiterCfg(
                capacity=int(getattr(settings, "RL_ACCOUNT_CAP", account.capacity)),
                window_sec=float(getattr(settings, "RL_ACCOUNT_WINDOW_SEC", account.window_sec)),
            )

        super().__init__(
            buckets={
                "orders": TokenBucket(orders.capacity, orders.window_sec),
                "market_data": TokenBucket(market.capacity, market.window_sec),
                "account": TokenBucket(account.capacity, account.window_sec),
                # можно добавить "http" для входящего трафика
            }
        )
