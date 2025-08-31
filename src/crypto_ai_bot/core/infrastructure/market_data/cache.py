from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from typing import Any


class TTLCache:
    """Простой in-memory кэш с TTL в секундах."""

    def __init__(self, ttl_sec: float = 30.0) -> None:
        self._ttl = float(ttl_sec)
        self._data: dict[tuple[Hashable, ...], tuple[float, Any]] = {}

    def _now(self) -> float:
        return time.time()

    def get(self, key: tuple[Hashable, ...]) -> Any | None:
        rec = self._data.get(key)
        if not rec:
            return None
        ts, val = rec
        if self._now() - ts <= self._ttl:
            return val
        self._data.pop(key, None)
        return None

    def put(self, key: tuple[Hashable, ...], value: Any) -> None:
        self._data[key] = (self._now(), value)

    def wrap(self, func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args, **kwargs):
            key = (func.__name__,) + tuple(args) + tuple(sorted(kwargs.items()))
            v = self.get(key)
            if v is not None:
                return v
            v = func(*args, **kwargs)
            self.put(key, v)
            return v
        return wrapped
