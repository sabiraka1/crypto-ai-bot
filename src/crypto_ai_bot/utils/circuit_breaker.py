from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable, Dict


class CircuitBreaker:
    def __init__(self) -> None:
        self.state: Dict[str, str] = {}
        self.fail_count: Dict[str, int] = {}
        self.open_until: Dict[str, float] = {}
        self.transitions_log: deque[tuple[str, str, str, float]] = deque(maxlen=100)
        self.last_errors: Dict[str, str] = {}

    def _set_state(self, key: str, new_state: str) -> None:
        old = self.state.get(key, "closed")
        if old != new_state:
            self.transitions_log.append((key, old, new_state, time.time()))
        self.state[key] = new_state

    def get_state(self, key: str) -> str:
        return self.state.get(key, "closed")

    def get_stats(self, key: str) -> Dict[str, Any]:
        return {
            "state": self.get_state(key),
            "fails": self.fail_count.get(key, 0),
            "open_until": self.open_until.get(key, 0),
            "last_error": self.last_errors.get(key),
            "transitions": [t for t in list(self.transitions_log) if t[0] == key][-10:],
        }

    def call(
        self,
        fn: Callable[[], Any],
        *,
        key: str,
        timeout: float,
        fail_threshold: int,
        open_seconds: float,
    ) -> Any:
        now = time.time()
        if self.get_state(key) == "open" and self.open_until.get(key, 0) > now:
            raise RuntimeError("circuit_open")

        if self.get_state(key) == "open" and self.open_until.get(key, 0) <= now:
            self._set_state(key, "half-open")

        start = time.perf_counter()
        try:
            result = fn()
            self.fail_count[key] = 0
            self._set_state(key, "closed")
            return result
        except Exception as exc:  # noqa: BLE001
            self.last_errors[key] = str(exc)
            self.fail_count[key] = self.fail_count.get(key, 0) + 1
            if self.fail_count[key] >= fail_threshold:
                self._set_state(key, "open")
                self.open_until[key] = now + open_seconds
            raise
        finally:
            _ = time.perf_counter() - start
