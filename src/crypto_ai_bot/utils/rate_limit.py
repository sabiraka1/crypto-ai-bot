from __future__ import annotations

import time
import threading
from typing import Callable, Optional, Dict, Any

try:
    from crypto_ai_bot.utils import metrics
except Exception:  # very early import
    class _M:
        @staticmethod
        def inc(*a, **k): pass
    metrics = _M()

class RateLimitExceeded(RuntimeError):
    pass

class _Bucket:
    __slots__ = ("capacity", "tokens", "refill_rate", "updated_at")
    def __init__(self, capacity: int, period: float) -> None:
        self.capacity = max(1, int(capacity))
        self.tokens = float(self.capacity)
        self.refill_rate = float(self.capacity) / float(period) if period > 0 else float("inf")
        self.updated_at = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.updated_at
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.updated_at = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

class RateLimiter:
    """
    Потокобезопасный токен-бакет по ключам.
    """
    def __init__(self) -> None:
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str, capacity: int, period: float) -> bool:
        with self._lock:
            b = self._buckets.get(key)
            if b is None or (b.capacity != capacity):
                b = _Bucket(capacity, period)
                self._buckets[key] = b
        ok = b.allow()
        return ok

_GLOBAL_LIM = RateLimiter()

def rate_limit(*, calls: int = 10, period: float = 1.0,
               key_fn: Optional[Callable[..., str]] = None,
               calls_attr: Optional[str] = None,
               period_attr: Optional[str] = None,
               raise_on_violation: bool = True):
    """
    Декоратор rate-limit с токен-бакетом.
    - calls/period — дефолтные лимиты;
    - key_fn(args, kwargs) -> str — формирует ключ; если не задано, используется имя функции;
    - calls_attr/period_attr — имена атрибутов в cfg (args[0]) для динамических лимитов;
    - raise_on_violation — если True, бросает RateLimitExceeded; иначе возвращает dict с ошибкой.
    """
    def _decorator(fn: Callable):
        fname = fn.__name__
        def _wrapper(*args, **kwargs):
            # пытаемся достать cfg из первого позиционного аргумента (по сигнатурам use-cases)
            cfg = args[0] if args else None

            eff_calls = calls
            eff_period = period
            if calls_attr and cfg is not None and hasattr(cfg, calls_attr):
                try:
                    eff_calls = int(getattr(cfg, calls_attr))
                except Exception:
                    eff_calls = calls
            if period_attr and cfg is not None and hasattr(cfg, period_attr):
                try:
                    eff_period = float(getattr(cfg, period_attr))
                except Exception:
                    eff_period = period

            if key_fn is not None:
                try:
                    key = key_fn(*args, **kwargs)
                except Exception:
                    key = fname
            else:
                key = fname

            ok = _GLOBAL_LIM.check(key, capacity=max(1, int(eff_calls)), period=max(0.001, float(eff_period)))
            if not ok:
                metrics.inc("rate_limit_exceeded_total", {"fn": fname, "key": key})
                if raise_on_violation:
                    raise RateLimitExceeded(f"rate_limited: key={key} calls={eff_calls}/period={eff_period}")
                return {"status": "rate_limited", "key": key, "calls": eff_calls, "period": eff_period}
            return fn(*args, **kwargs)
        _wrapper.__name__ = fn.__name__
        _wrapper.__doc__ = fn.__doc__
        _wrapper.__qualname__ = fn.__qualname__
        return _wrapper
    return _decorator
