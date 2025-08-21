from __future__ import annotations
import time
import asyncio
from typing import Any, Callable, Awaitable
from crypto_ai_bot.utils.exceptions import CircuitBreakerOpen


class CircuitBreaker:
    """Реализация паттерна Circuit Breaker.
    Состояния: CLOSED → OPEN → HALF_OPEN → CLOSED.
    - CLOSED: пропускает вызовы; при N подряд ошибках переходит в OPEN.
    - OPEN: мгновенно отклоняет вызовы (fallback или исключение), пока не истечёт таймаут.
    - HALF_OPEN: единичная проба; успех → CLOSED, ошибка → OPEN и таймер заново.
    """

    def __init__(
        self,
        *,
        name: str = "circuit",
        timeout: float = 60.0,
        threshold: int = 5,
        fallback: Callable[..., Any] | Callable[..., Awaitable[Any]] | Any | None = None,
    ) -> None:
        self.name = name
        self.timeout = float(timeout)
        self.threshold = int(threshold)
        self.fallback = fallback
        self.state: str = "closed"
        self._fail_count = 0
        self._opened_at: float | None = None

    def __call__(self, fn: Callable[..., Any] | Callable[..., Awaitable[Any]]):
        if asyncio.iscoroutinefunction(fn):
            async def _aw(*args, **kwargs):
                return await self._call_async(fn, *args, **kwargs)
            return _aw
        else:
            def _w(*args, **kwargs):
                return self._call_sync(fn, *args, **kwargs)
            return _w

    # --- sync path ---
    def _call_sync(self, fn: Callable[..., Any], *args, **kwargs):
        if self.state == "open":
            if self._opened_at is not None and (time.time() - self._opened_at) < self.timeout:
                return self._fail_fast(*args, **kwargs)
            self.state = "half_open"
        try:
            res = fn(*args, **kwargs)
        except Exception as err:  # noqa: BLE001
            return self._on_failure(err, *args, **kwargs)
        else:
            return self._on_success(res)

    # --- async path ---
    async def _call_async(self, fn: Callable[..., Awaitable[Any]], *args, **kwargs):
        if self.state == "open":
            if self._opened_at is not None and (time.time() - self._opened_at) < self.timeout:
                return self._fail_fast(*args, **kwargs)
            self.state = "half_open"
        try:
            res = await fn(*args, **kwargs)
        except Exception as err:  # noqa: BLE001
            return self._on_failure(err, *args, **kwargs)
        else:
            return self._on_success(res)

    def _on_failure(self, err: Exception, *args, **kwargs):
        if self.state == "half_open":
            self.state = "open"
            self._opened_at = time.time()
            self._fail_count = 0
            return self._fail_fast(*args, **kwargs)
        self._fail_count += 1
        if self._fail_count >= self.threshold:
            self.state = "open"
            self._opened_at = time.time()
            self._fail_count = 0
            return self._fail_fast(*args, **kwargs)
        raise err

    def _on_success(self, result: Any):
        self._fail_count = 0
        if self.state in ("half_open", "open"):
            self.state = "closed"
        return result

    def _fail_fast(self, *args, **kwargs):
        if self.fallback is not None:
            fb = self.fallback
            if callable(fb):
                if asyncio.iscoroutinefunction(fb):
                    return asyncio.get_event_loop().run_until_complete(fb(*args, **kwargs))
                return fb(*args, **kwargs)
            return fb
        raise CircuitBreakerOpen(f"CircuitBreaker '{self.name}' открыт (OPEN)")