# src/crypto_ai_bot/utils/rate_limit.py
from __future__ import annotations

import asyncio
import functools
import threading
import time
from collections import deque
from typing import Callable, Deque, Optional

from . import metrics


class RateLimitExceeded(Exception):
    pass


def rate_limit(*, max_calls: Optional[int] = None, window: Optional[int] = None, limit: Optional[int] = None, per: Optional[int] = None):
    """
    Универсальный декоратор:
      @rate_limit(max_calls=60, window=60)        # рекомендованный синтаксис (Word)
    Поддержка старого алиаса:
      @rate_limit(limit=60, per=60)
    Окно — в секундах. Счётчик — по количеству вызовов.
    """
    calls = int(max_calls if max_calls is not None else (limit if limit is not None else 0))
    win = int(window if window is not None else (per if per is not None else 0))
    if calls <= 0 or win <= 0:
        # no-op
        def passthrough(fn):
            return fn
        return passthrough

    lock = threading.RLock()
    q: Deque[float] = deque()

    def _touch(now: float):
        while q and (now - q[0]) > win:
            q.popleft()

    def decorator(fn: Callable):
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def aw(*args, **kwargs):
                now = time.monotonic()
                with lock:
                    _touch(now)
                    if len(q) >= calls:
                        metrics.inc("rate_limit_exceeded_total", {"func": fn.__name__})
                        raise RateLimitExceeded(f"Rate limit exceeded: {calls}/{win}s")
                    q.append(now)
                return await fn(*args, **kwargs)
            return aw
        else:
            @functools.wraps(fn)
            def w(*args, **kwargs):
                now = time.monotonic()
                with lock:
                    _touch(now)
                    if len(q) >= calls:
                        metrics.inc("rate_limit_exceeded_total", {"func": fn.__name__})
                        raise RateLimitExceeded(f"Rate limit exceeded: {calls}/{win}s")
                    q.append(now)
                return fn(*args, **kwargs)
            return w
    return decorator
