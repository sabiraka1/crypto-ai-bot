from __future__ import annotations
import time
from typing import Optional, Dict, Any, List

__all__ = ["CircuitBreaker", "HALF_OPEN", "OPEN", "CLOSED"]

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half-open"

class CircuitBreaker:
    """
    Простой CB с журналом переходов и stats.
    Поля:
      - state: closed|open|half-open
      - opened_at_ms: когда открыли (для таймаута)
      - fail_count / success_count
      - transitions: список {"ts":..,"from":..,"to":..,"reason":..}
    """
    def __init__(self, *, open_timeout_ms: int = 10_000, max_failures: int = 3):
        self.open_timeout_ms = int(open_timeout_ms)
        self.max_failures = int(max_failures)
        self.state = CLOSED
        self.opened_at_ms: Optional[int] = None
        self.fail_count = 0
        self.success_count = 0
        self.transitions: List[Dict[str, Any]] = []

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    # ----- transitions / logging -----
    def _transition(self, to_state: str, reason: str) -> None:
        prev = self.state
        self.state = to_state
        if to_state == OPEN:
            self.opened_at_ms = self._now_ms()
        elif to_state == CLOSED:
            self.opened_at_ms = None
            self.fail_count = 0
        self.transitions.append({
            "ts": self._now_ms(),
            "from": prev, "to": to_state, "reason": str(reason),
        })

    # ----- API -----
    def allow(self) -> bool:
        if self.state == CLOSED:
            return True
        if self.state == OPEN:
            if self.opened_at_ms is None:
                return False
            if self._now_ms() - self.opened_at_ms >= self.open_timeout_ms:
                self._transition(HALF_OPEN, "timeout_expired")
                return True
            return False
        if self.state == HALF_OPEN:
            return True
        return False

    def on_success(self) -> None:
        self.success_count += 1
        if self.state in (HALF_OPEN, OPEN):
            self._transition(CLOSED, "success")
        # в closed остаёмся closed

    def on_failure(self, *, reason: str = "error") -> None:
        self.fail_count += 1
        if self.state == CLOSED and self.fail_count >= self.max_failures:
            self._transition(OPEN, reason)
        elif self.state == HALF_OPEN:
            self._transition(OPEN, reason)
        # если уже OPEN — остаёмся OPEN

    # статистика для health/метрик
    def get_stats(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "fail_count": self.fail_count,
            "success_count": self.success_count,
            "opened_for_ms": 0 if self.opened_at_ms is None else max(0, self._now_ms() - self.opened_at_ms),
            "transitions": list(self.transitions[-50:]),  # хвост журнала
        }
