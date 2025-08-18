from __future__ import annotations
import time
from typing import List, Dict, Any, Optional

class CircuitBreaker:
    """
    Простой полублокирующий Circuit Breaker со статусами:
    closed → open → half-open → closed
    Ведёт transitions_log и отдаёт get_stats().
    """
    def __init__(self, name: str = "breaker", failure_threshold: int = 5,
                 recovery_time_seconds: float = 30.0) -> None:
        self.name = name
        self.failure_threshold = int(failure_threshold)
        self.recovery_time = float(recovery_time_seconds)
        self._state = "closed"
        self._failures = 0
        self._opened_at: Optional[float] = None
        self.transitions_log: List[Dict[str, Any]] = []

    def _transition(self, new_state: str, reason: str) -> None:
        old = self._state
        if old == new_state:  # нет смысла
            return
        self._state = new_state
        self.transitions_log.append({
            "ts": int(time.time() * 1000),
            "from": old,
            "to": new_state,
            "reason": reason,
            "name": self.name,
        })

    def _on_failure(self, err: BaseException) -> None:
        self._failures += 1
        if self._state == "closed" and self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()
            self._transition("open", f"failures={self._failures}")
        elif self._state == "half-open":
            # при провале в half-open снова уходим в open
            self._opened_at = time.monotonic()
            self._transition("open", "half-open failure")

    def _on_success(self) -> None:
        self._failures = 0
        if self._state in ("open", "half-open"):
            self._transition("closed", "success")

    def __enter__(self):
        # проверка состояния
        if self._state == "open":
            elapsed = time.monotonic() - (self._opened_at or 0.0)
            if elapsed >= self.recovery_time:
                self._transition("half-open", "recovery window passed")
            else:
                raise RuntimeError(f"CircuitBreaker[{self.name}] is OPEN")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None:
            self._on_success()
            return False
        self._on_failure(exc)   # тип не глотаем
        return False

    def get_stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self._state,
            "failures": self._failures,
            "recovery_time": self.recovery_time,
            "opened_at_monotonic": self._opened_at,
            "transitions": list(self.transitions_log)[-50:],  # не распухать
        }
