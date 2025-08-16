# src/crypto_ai_bot/utils/rate_limit.py
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, Optional

from . import metrics


class RateLimitExceeded(RuntimeError):
    """Лимит запросов превышен."""


@dataclass
class _Bucket:
    window: float
    max_calls: int
    ticks: Deque[float] = field(default_factory=deque)


class RateLimiter:
    """
    Скользящее окно в памяти процесса.
    Подходит для одного воркера. Для мульти-инстансов — нужен внешний стор.
    """

    def __init__(self):
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str, *, max_calls: int, window_seconds: float) -> bool:
        now = time.monotonic()
        async with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(window=window_seconds, max_calls=max_calls)
                self._buckets[key] = b
            # чистим старые тики
            while b.ticks and (now - b.ticks[0]) > b.window:
                b.ticks.popleft()
            if len(b.ticks) < b.max_calls:
                b.ticks.append(now)
                metrics.inc("rate_limit_pass_total", {"key": key})
                return True
            else:
                metrics.inc("rate_limit_block_total", {"key": key})
                return False


_global_limiter = RateLimiter()


def rate_limit(*, key: Callable[..., str] | str, max_calls: int, window_seconds: float, mode: str = "raise"):
    """
    Декоратор для sync/async функций. mode:
      - "raise" (по умолчанию): бросает RateLimitExceeded
      - "sleep": спит до освобождения окна, затем выполняет (только для async)
    """
    def _decorator(func):
        is_async = asyncio.iscoroutinefunction(func)

        if is_async:
            async def _aw(*args, **kwargs):
                k = key(*args, **kwargs) if callable(key) else str(key)
                ok = await _global_limiter.allow(k, max_calls=max_calls, window_seconds=window_seconds)
                if not ok:
                    if mode == "sleep":
                        # ждём до ближайшего освобождения окна (грубая оценка)
                        await asyncio.sleep(window_seconds / max_calls)
                    else:
                        raise RateLimitExceeded(f"rate limit exceeded for {k}")
                return await func(*args, **kwargs)
            return _aw
        else:
            def _sw(*args, **kwargs):
                # sync обёртка: внутри откроем цикл и подождём allow()
                k = key(*args, **kwargs) if callable(key) else str(key)
                loop = asyncio.get_event_loop() if asyncio.get_event_loop_policy().get_event_loop() else asyncio.new_event_loop()
                try:
                    ok = loop.run_until_complete(_global_limiter.allow(k, max_calls=max_calls, window_seconds=window_seconds))
                except RuntimeError:
                    # если мы уже в работающем event loop (например, uvicorn) — используем asyncio.run()
                    ok = asyncio.run(_global_limiter.allow(k, max_calls=max_calls, window_seconds=window_seconds))
                if not ok:
                    if mode == "sleep":
                        time.sleep(window_seconds / max_calls)
                    else:
                        raise RateLimitExceeded(f"rate limit exceeded for {k}")
                return func(*args, **kwargs)
            return _sw
    return _decorator
