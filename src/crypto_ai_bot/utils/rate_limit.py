# src/crypto_ai_bot/utils/rate_limit.py
from __future__ import annotations

import time
import threading
import functools
import inspect
from collections import deque
from typing import Callable, Deque, Dict, Optional, Any

__all__ = ["rate_limit", "RateLimitExceeded"]


class RateLimitExceeded(RuntimeError):
    pass


class _Limiter:
    def __init__(self, max_calls: int, window: float) -> None:
        self.max_calls = int(max_calls)
        self.window = float(window)
        self.lock = threading.RLock()
        self.calls: Deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        with self.lock:
            while self.calls and self.calls[0] < cutoff:
                self.calls.popleft()
            if len(self.calls) >= self.max_calls:
                return False
            self.calls.append(now)
            return True


def rate_limit(*dargs: Any, **dkwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Унифицированный декоратор:
      @rate_limit(max_calls=60, window=60)      # спецификация
      @rate_limit(limit=60, per=60)             # старый вариант (синонимы)
    Работает и для sync, и для async функций.
    """
    max_calls = dkwargs.get("max_calls", dkwargs.get("limit"))
    window = dkwargs.get("window", dkwargs.get("per"))
    if max_calls is None or window is None:
        raise TypeError("rate_limit requires (max_calls, window) or (limit, per)")

    limiter = _Limiter(int(max_calls), float(window))

    def _decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        is_coro = inspect.iscoroutinefunction(fn)

        @functools.wraps(fn)
        async def _async_wrapped(*args: Any, **kwargs: Any) -> Any:
            if not limiter.allow():
                try:
                    from . import metrics  # ленивая загрузка, чтобы не плодить зависимостей
                    metrics.inc("rate_limit_exceeded_total", {"fn": fn.__name__})
                except Exception:
                    pass
                raise RateLimitExceeded(f"rate limit exceeded: {max_calls} calls / {window}s")
            return await fn(*args, **kwargs)

        @functools.wraps(fn)
        def _sync_wrapped(*args: Any, **kwargs: Any) -> Any:
            if not limiter.allow():
                try:
                    from . import metrics
                    metrics.inc("rate_limit_exceeded_total", {"fn": fn.__name__})
                except Exception:
                    pass
            # поднимаем исключение для вызывающей стороны (UC ловят и возвращают статус)
                raise RateLimitExceeded(f"rate limit exceeded: {max_calls} calls / {window}s")
            return fn(*args, **kwargs)

        return _async_wrapped if is_coro else _sync_wrapped

    # Поддержка как с параметрами, так и без (но у нас всегда с параметрами)
    if dargs and callable(dargs[0]):
        return _decorate(dargs[0])
    return _decorate
