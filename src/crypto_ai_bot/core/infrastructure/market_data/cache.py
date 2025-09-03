from __future__ import annotations

import time
from typing import Any, Generic, TypeVar


T = TypeVar("T")

class TTLCache(Generic[T]):
    def __init__(self, ttl_sec: float = 30.0) -> None:
        self._ttl = float(ttl_sec)
        self._data: dict[Any, tuple[float, T]] = {}

    def get(self, key: Any) -> T | None:
        now = time.time()
        rec = self._data.get(key)
        if not rec:
            return None
        ts, val = rec
        if now - ts > self._ttl:
            self._data.pop(key, None)
            return None
        return val

    def put(self, key: Any, val: T) -> None:
        self._data[key] = (time.time(), val)
