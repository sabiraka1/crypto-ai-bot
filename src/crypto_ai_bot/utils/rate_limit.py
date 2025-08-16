from __future__ import annotations

import time
import threading
from collections import deque
from typing import Dict, Deque

class RateLimiter:
    """
    Простой in-memory rate limiter (скользящее окно).
    Не кластерный. Подходит для одного процесса FastAPI.
    """
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: Dict[str, Deque[float]] = {}

    def allow(self, key: str, calls: int, per_seconds: float) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._buckets.setdefault(key, deque())
            # выкинем устаревшие метки времени
            cutoff = now - float(per_seconds)
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) < int(calls):
                q.append(now)
                return True
            return False

# Глобальный экземпляр
_global_limiter = RateLimiter()

def allow(key: str, calls: int, per_seconds: float) -> bool:
    return _global_limiter.allow(key, calls, per_seconds)
