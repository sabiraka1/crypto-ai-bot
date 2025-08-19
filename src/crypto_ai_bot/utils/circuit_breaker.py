from __future__ import annotations

import time
from typing import Any, Dict, Optional


class CircuitBreaker:
    """
    Простой, но полноценный circuit breaker:
      - CLOSED: пропускает вызовы, собирает статистику
      - OPEN: блокирует вызовы до истечения open_timeout_sec
      - HALF_OPEN: допускает ограниченное число проб (half_open_max_calls)
    Переходы:
      CLOSED --(ошибки >= fail_threshold)--> OPEN
      OPEN --(по таймауту)--> HALF_OPEN
      HALF_OPEN --(успех)--> CLOSED; --(ошибка)--> OPEN
    """

    def __init__(
        self,
        name: str,
        *,
        fail_threshold: int = 5,
        open_timeout_sec: float = 30.0,
        half_open_max_calls: int = 1,
        window_sec: float = 60.0,
    ) -> None:
        self.name = name
        self.fail_threshold = int(max(1, fail_threshold))
        self.open_timeout_sec = float(max(0.1, open_timeout_sec))
        self.half_open_max_calls = int(max(1, half_open_max_calls))
        self.window_sec = float(max(1.0, window_sec))

        self._state: str = "closed"
        self._opened_at: float = 0.0
        self._half_open_remaining: int = 0

        self._last_reset: float = time.monotonic()
        self._errors: int = 0
        self._errors_by_kind: Dict[str, int] = {}

    # --------- state / metrics ---------

    def state(self) -> str:
        # auto-transition OPEN -> HALF_OPEN по таймауту
        if self._state == "open":
            if (time.monotonic() - self._opened_at) >= self.open_timeout_sec:
                self._state = "half_open"
                self._half_open_remaining = self.half_open_max_calls
        return self._state

    def metrics(self) -> Dict[str, Any]:
        return {
            "state": self.state(),
            "errors_total": self._errors,
            "errors_by_kind": dict(self._errors_by_kind),
            "opened_ago": (time.monotonic() - self._opened_at) if self._opened_at else None,
        }

    # --------- control ---------

    def allow(self) -> bool:
        st = self.state()
        if st == "closed":
            return True
        if st == "open":
            return False
        # half_open
        if self._half_open_remaining > 0:
            self._half_open_remaining -= 1
            return True
        return False

    def record_success(self) -> None:
        st = self.state()
        if st == "half_open":
            self._to_closed()
        elif st == "closed":
            # периодическая санация счётчика ошибок
            self._maybe_decay()
        # open -> success невозможен (allow() не даст), оставим как no-op

    def record_error(self, kind: str, err: Exception) -> None:
        self._errors += 1
        self._errors_by_kind[kind] = self._errors_by_kind.get(kind, 0) + 1

        st = self.state()
        if st == "closed":
            self._maybe_decay()
            if self._errors >= self.fail_threshold:
                self._to_open()
        elif st == "half_open":
            # не прошли пробу — обратно в OPEN
            self._to_open()
        elif st == "open":
            # остаёмся в open
            pass

    # --------- internals ---------

    def _maybe_decay(self) -> None:
        now = time.monotonic()
        if (now - self._last_reset) >= self.window_sec:
            self._errors = 0
            self._errors_by_kind.clear()
            self._last_reset = now

    def _to_open(self) -> None:
        self._state = "open"
        self._opened_at = time.monotonic()

    def _to_closed(self) -> None:
        self._state = "closed"
        self._opened_at = 0.0
        self._half_open_remaining = 0
        self._errors = 0
        self._errors_by_kind.clear()
        self._last_reset = time.monotonic()
