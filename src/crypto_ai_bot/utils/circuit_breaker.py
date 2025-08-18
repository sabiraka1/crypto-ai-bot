# src/crypto_ai_bot/utils/circuit_breaker.py
from __future__ import annotations

import time
from typing import Any, Dict, Optional


class CircuitBreaker:
    """
    Минимальный счётчик для агрегирования статуса внешних вызовов.
    Не размыкает цепь, но копит статистику: попытки/успехи/ошибки по категориям.
    """
    def __init__(self, name: str) -> None:
        self.name = name
        self.reset()

    def reset(self) -> None:
        self.total = 0
        self.success = 0
        self.fail = 0
        self.by_kind: Dict[str, int] = {}
        self.last_error: Optional[str] = None
        self.last_ts_ms: Optional[int] = None

    def record_success(self) -> None:
        self.total += 1
        self.success += 1
        self.last_ts_ms = int(time.time() * 1000)

    def record_error(self, kind: str, err: Exception) -> None:
        self.total += 1
        self.fail += 1
        self.by_kind[kind] = self.by_kind.get(kind, 0) + 1
        self.last_error = f"{type(err).__name__}: {err}"
        self.last_ts_ms = int(time.time() * 1000)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "total": self.total,
            "success": self.success,
            "fail": self.fail,
            "by_kind": dict(self.by_kind),
            "last_error": self.last_error,
            "last_ts_ms": self.last_ts_ms,
        }
