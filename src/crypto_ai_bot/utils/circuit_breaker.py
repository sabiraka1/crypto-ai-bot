from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

class CircuitBreaker:
    """
    Простой circuit breaker с логом переходов, последними ошибками и статистикой.
    Метод call(fn, *, key, timeout, fail_threshold, open_seconds).
    """
    def __init__(self) -> None:
        self._lock = threading.RLock()
        # per-key state
        self._state: Dict[str, str] = {}  # closed|open|half-open
        self._fails: Dict[str, int] = {}
        self._last_open: Dict[str, float] = {}
        self._last_errors: Dict[str, str] = {}
        self._transitions: Dict[str, list[tuple[float, str]]] = {}  # (ts, state)

    def _set_state(self, key: str, state: str) -> None:
        with self._lock:
            self._state[key] = state
            self._transitions.setdefault(key, []).append((time.time(), state))
            if state == "open":
                self._last_open[key] = time.time()

    def get_stats(self, key: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if key is not None:
                return {
                    "state": self._state.get(key, "closed"),
                    "fails": self._fails.get(key, 0),
                    "last_open_ts": self._last_open.get(key),
                    "last_error": self._last_errors.get(key),
                    "transitions": list(self._transitions.get(key, [])),
                }
            # aggregated
            return {k: self.get_stats(k) for k in self._state.keys()}

    def call(self, fn, *, key: str, timeout: float, fail_threshold: int, open_seconds: float) -> Any:
        now = time.time()
        with self._lock:
            state = self._state.get(key, "closed")
            if state == "open":
                opened = self._last_open.get(key, now)
                if (now - opened) >= open_seconds:
                    self._state[key] = "half-open"
                    self._transitions.setdefault(key, []).append((now, "half-open"))
                else:
                    raise TimeoutError("circuit_open")
        # execute
        t0 = time.perf_counter()
        try:
            res = fn()
            dt = time.perf_counter() - t0
            if dt > timeout:
                raise TimeoutError("timeout")
            # success path
            with self._lock:
                self._fails[key] = 0
                if self._state.get(key, "closed") != "closed":
                    self._set_state(key, "closed")
            return res
        except Exception as e:
            with self._lock:
                self._fails[key] = self._fails.get(key, 0) + 1
                self._last_errors[key] = repr(e)
                if self._fails[key] >= fail_threshold:
                    self._set_state(key, "open")
            raise
