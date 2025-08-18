# src/crypto_ai_bot/utils/cache.py
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple


class TTLCache:
    """
    Очень простой потокобезопасный TTL-кэш в памяти.
    Используется для market_context.* чтобы не грузить внешние API слишком часто.
    """
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: Dict[str, Tuple[float, Any]] = {}  # key -> (expires_at, value)

    def get(self, key: str) -> Optional[Any]:
        now = time.monotonic()
        with self._lock:
            it = self._data.get(key)
            if not it:
                return None
            exp, val = it
            if exp <= now:
                # просрочено
                try:
                    del self._data[key]
                except Exception:
                    pass
                return None
            return val

    def set(self, key: str, value: Any, ttl_sec: float) -> None:
        exp = time.monotonic() + max(0.0, float(ttl_sec))
        with self._lock:
            self._data[key] = (exp, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


GLOBAL_CACHE = TTLCache()
