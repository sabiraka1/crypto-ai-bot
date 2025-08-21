## `utils/circuit_breaker.py`
from __future__ import annotations
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Type, Tuple
from .exceptions import CircuitOpenError, TransientError
__all__ = ["CircuitBreaker", "State"]
class State:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
@dataclass
class CircuitBreaker:
    failures_threshold: int = 5
    open_timeout_ms: int = 30_000
    half_open_successes_to_close: int = 2
    retry_exceptions: Tuple[Type[BaseException], ...] = (TransientError, TimeoutError, ConnectionError)
    def __post_init__(self) -> None:
        self._state = State.CLOSED
        self._failures = 0
        self._half_open_successes = 0
        self._opened_at_ms: Optional[int] = None
        self._lock = threading.Lock()
    def _now_ms(self) -> int:
        return int(time.time() * 1000)
    def _transition_to(self, state: str) -> None:
        self._state = state
        if state == State.OPEN:
            self._opened_at_ms = self._now_ms()
        else:
            self._opened_at_ms = None
        self._failures = 0
        self._half_open_successes = 0
    def allow(self) -> bool:
        with self._lock:
            if self._state == State.CLOSED:
                return True
            if self._state == State.OPEN:
                assert self._opened_at_ms is not None
                if self._now_ms() - self._opened_at_ms >= self.open_timeout_ms:
                    self._transition_to(State.HALF_OPEN)
                    return True
                return False
            if self._state == State.HALF_OPEN:
                return True
            return False
    def on_success(self) -> None:
        with self._lock:
            if self._state == State.CLOSED:
                self._failures = 0
                return
            if self._state == State.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.half_open_successes_to_close:
                    self._transition_to(State.CLOSED)
    def on_failure(self, exc: BaseException) -> None:
        with self._lock:
            if not isinstance(exc, self.retry_exceptions):
                self._transition_to(State.OPEN)
                return
            if self._state in {State.CLOSED, State.HALF_OPEN}:
                self._failures += 1
                if self._failures >= self.failures_threshold:
                    self._transition_to(State.OPEN)
    def run(self, func: Callable, *args, **kwargs):
        if not self.allow():
            raise CircuitOpenError("circuit is OPEN")
        try:
            result = func(*args, **kwargs)
        except BaseException as exc:  # broad by design
            self.on_failure(exc)
            raise
        else:
            self.on_success()
            return result
    async def run_async(self, func: Callable, *args, **kwargs):
        if not self.allow():
            raise CircuitOpenError("circuit is OPEN")
        try:
            result = await func(*args, **kwargs)
        except BaseException as exc:  # broad by design
            self.on_failure(exc)
            raise
        else:
            self.on_success()
            return result
    @property
    def state(self) -> str:
        return self._state
