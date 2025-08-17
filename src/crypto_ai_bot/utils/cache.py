# src/crypto_ai_bot/utils/cache.py
from __future__ import annotations
import time
from typing import Any, Dict, Tuple, Optional

class TTLCache:
    def __init__(self, ttl_sec: int = 60, maxsize: int = 1024) -> None:
        self.ttl = int(ttl_sec)
        self.maxsize = int(maxsize)
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        item = self._store.get(key)
        if not item:
            return None
        ts, val = item
        if now - ts > self.ttl:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any) -> None:
        if len(self._store) >= self.maxsize:
            # простейшая стратегия: удалить самый старый
            k = min(self._store.keys(), key=lambda k: self._store[k][0])
            self._store.pop(k, None)
        self._store[key] = (time.time(), value)
