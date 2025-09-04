from __future__ import annotations

import asyncio
import time
from typing import Any


class CircuitBreaker:
    """
    Асинхронный circuit breaker со стейт-машиной:
      closed -> open (на reset_timeout) -> half-open (одна попытка) -> closed.

    Использование:
        cb = CircuitBreaker(name="broker", failure_threshold=5, reset_timeout_sec=10)
        async with cb:
            await do_call()
    """

    def __init__(self, *, name: str = "cb", failure_threshold: int = 5, reset_timeout_sec: float = 10.0):
        self.name = name
        self.failure_threshold = int(failure_threshold)
        self.reset_timeout = float(reset_timeout_sec)
        self._state = "closed"
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> None:
        async with self._lock:
            if self._state == "open":
                if self._opened_at and (time.time() - self._opened_at) >= self.reset_timeout:
                    self._state = "half-open"
                    self._failures = 0
                else:
                    raise RuntimeError(f"{self.name}: open")
            # closed или half-open — разрешаем попытку

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool | None:
        async with self._lock:
            if exc is None:
                self._state = "closed"
                self._failures = 0
                self._opened_at = None
            else:
                self._failures += 1
                if self._failures >= self.failure_threshold or self._state == "half-open":
                    self._state = "open"
                    self._opened_at = time.time()
                return False  # не подавляем исключение
        return None
