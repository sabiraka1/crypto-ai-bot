# src/crypto_ai_bot/utils/rate_ops.py
from __future__ import annotations
import time
from typing import Dict, Tuple

class RateLimiter:
    """Токен-бакет per-key (например, key='place_order:BTC/USDT:buy')."""
    def __init__(self, default_rps: float = 1.0, default_burst: float = 2.0):
        self.default_rps = float(default_rps)
        self.default_burst = float(default_burst)
        self._buckets: Dict[str, Tuple[float, float, float]] = {}  # key -> (tokens, ts, cap)

    def allow(self, key: str, *, rps: float | None = None, burst: float | None = None) -> bool:
        rate = float(rps or self.default_rps)
        cap  = float(burst or self.default_burst)
        now = time.time()
        tokens, ts, _ = self._buckets.get(key, (cap, now, cap))
        tokens = min(cap, tokens + (now - ts) * rate)
        if tokens < 1.0:
            self._buckets[key] = (tokens, now, cap)
            return False
        self._buckets[key] = (tokens - 1.0, now, cap)
        return True

GLOBAL_RATE_LIMITER = RateLimiter()
