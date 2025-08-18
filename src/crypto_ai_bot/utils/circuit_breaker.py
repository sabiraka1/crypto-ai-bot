from __future__ import annotations
import time
from typing import Callable, Any, Optional


class CircuitBreaker:
    """
    Простой полурегулируемый Circuit Breaker:
      - failure_threshold: сколько подряд ошибок, чтобы перейти в OPEN
      - reset_timeout_sec: сколько ждать в OPEN, прежде чем попробовать HALF-OPEN
      - success_threshold: сколько подряд успешных вызовов в HALF-OPEN, чтобы закрыть

    Использование:
      cb = CircuitBreaker()
      result = cb.call(fn, on_error=...)
    """
    def __init__(self,
                 failure_threshold: int = 5,
                 reset_timeout_sec: float = 10.0,
                 success_threshold: int = 2):
        self.failure_threshold = max(1, int(failure_threshold))
        self.reset_timeout_sec = float(reset_timeout_sec)
        self.success_threshold = max(1, int(success_threshold))

        self._state = "CLOSED"        # CLOSED | OPEN | HALF_OPEN
        self._failures = 0
        self._successes = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        # автопереход OPEN -> HALF_OPEN по таймауту
        if self._state == "OPEN" and (time.time() - self._opened_at) >= self.reset_timeout_sec:
            self._state = "HALF_OPEN"
            self._successes = 0
            self._failures = 0
        return self._state

    def call(self, fn: Callable[[], Any], *, on_error: Optional[Callable[[Exception], None]] = None) -> Any:
        st = self.state
        if st == "OPEN":
            raise RuntimeError("circuit_open")

        try:
            result = fn()
            self._on_success()
            return result
        except Exception as e:
            if on_error:
                try:
                    on_error(e)
                except Exception:
                    pass
            self._on_failure()
            raise

    def _on_success(self) -> None:
        if self._state in ("CLOSED",):
            self._failures = 0
            return
        # HALF_OPEN
        self._successes += 1
        if self._successes >= self.success_threshold:
            self._state = "CLOSED"
            self._failures = 0
            self._successes = 0

    def _on_failure(self) -> None:
        if self._state in ("HALF_OPEN", "CLOSED"):
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._state = "OPEN"
                self._opened_at = time.time()
                self._successes = 0
