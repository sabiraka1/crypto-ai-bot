# src/crypto_ai_bot/utils/circuit_breaker.py
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout
import threading

from . import metrics


class CircuitOpenError(RuntimeError):
    """Запрос коротко замкнут: цепь открыта (open)."""


@dataclass
class _Entry:
    state: str = "closed"          # "closed" | "open" | "half-open"
    failures: int = 0
    opened_at: float = 0.0         # epoch when transitioned to open
    half_open_in_flight: int = 0   # для ограничения кол-ва проб в half-open


class CircuitBreaker:
    """
    Лёгкий circuit breaker:
      - closed: пропускает вызовы; при N подряд ошибках → open.
      - open: немедленно отклоняет до истечения open_seconds.
      - half-open: допускает до half_open_max_calls проб; на успех → closed; на ошибку → open.
    Поддерживает sync/async вызовы и опциональный timeout.
    """

    def __init__(
        self,
        *,
        fail_threshold: int = 5,
        open_seconds: float = 30.0,
        half_open_max_calls: int = 1,
        on_state_change: Optional[Callable[[str, str, str], None]] = None,  # (key, old, new)
        transient_exceptions: Tuple[type[BaseException], ...] = (Exception,),
    ) -> None:
        self.fail_threshold = int(fail_threshold)
        self.open_seconds = float(open_seconds)
        self.half_open_max_calls = int(half_open_max_calls)
        self.on_state_change = on_state_change
        self.transient_exceptions = transient_exceptions

        self._lock = threading.Lock()
        self._map: Dict[str, _Entry] = {}
        self._pool = ThreadPoolExecutor(max_workers=16)

    # ---------------------- общая внутренняя логика ----------------------

    def get_state(self, key: str) -> str:
        with self._lock:
            return self._map.get(key, _Entry()).state

    def _set_state(self, key: str, new_state: str) -> None:
        with self._lock:
            entry = self._map.setdefault(key, _Entry())
            old = entry.state
            if old == new_state:
                return
            entry.state = new_state
            if new_state == "open":
                entry.opened_at = time.time()
                entry.half_open_in_flight = 0
            elif new_state == "closed":
                entry.failures = 0
                entry.half_open_in_flight = 0
            elif new_state == "half-open":
                entry.half_open_in_flight = 0

        # метрики и колбэк — вне локов
        metrics.inc("broker_circuit_transition_total", {"key": key, "from": old, "to": new_state})
        if self.on_state_change:
            try:
                self.on_state_change(key, old, new_state)
            except Exception:
                pass

    def _should_open(self, entry: _Entry) -> bool:
        return entry.failures >= self.fail_threshold

    def _before_call(self, key: str) -> str:
        with self._lock:
            entry = self._map.setdefault(key, _Entry())
            now = time.time()
            if entry.state == "open":
                if (now - entry.opened_at) >= self.open_seconds:
                    # истёк период open → пробуем half-open
                    entry.state = "half-open"
                    entry.half_open_in_flight = 0
                else:
                    return "open"

            if entry.state == "half-open":
                if entry.half_open_in_flight >= self.half_open_max_calls:
                    return "open"  # считаем перегруз и режем
                entry.half_open_in_flight += 1
                return "half-open"

            return "closed"

    def _after_success(self, key: str, phase: str) -> None:
        with self._lock:
            entry = self._map.setdefault(key, _Entry())
            entry.failures = 0
            if phase == "half-open":
                entry.state = "closed"
                entry.half_open_in_flight = 0
        if phase == "half-open":
            self._set_state(key, "closed")

    def _after_failure(self, key: str, phase: str) -> None:
        with self._lock:
            entry = self._map.setdefault(key, _Entry())
            entry.failures += 1
            if phase == "half-open":
                # любой фейл в half-open → сразу open
                entry.state = "open"
                entry.opened_at = time.time()
                entry.half_open_in_flight = 0
            elif self._should_open(entry):
                entry.state = "open"
                entry.opened_at = time.time()
        # Обновим метрики переходов
        st = self.get_state(key)
        if st == "open":
            metrics.inc("broker_circuit_open_total", {"key": key})

    # ---------------------- публичные вызовы ----------------------

    def call(
        self,
        key: str,
        fn: Callable[..., Any],
        *args: Any,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Sync-вызов с опциональным timeout. Исключения транслируем наружу.
        Если цепь открыта — бросаем CircuitOpenError.
        """
        phase = self._before_call(key)
        if phase == "open":
            raise CircuitOpenError(f"circuit for {key!r} is open")

        t0 = time.perf_counter()
        try:
            if timeout is None:
                res = fn(*args, **kwargs)
            else:
                fut = self._pool.submit(fn, *args, **kwargs)
                res = fut.result(timeout=timeout)
            self._after_success(key, phase)
            metrics.observe("broker_call_seconds", time.perf_counter() - t0, {"key": key, "result": "ok"})
            return res
        except self.transient_exceptions as e:
            self._after_failure(key, phase)
            metrics.observe("broker_call_seconds", time.perf_counter() - t0, {"key": key, "result": "err"})
            raise
        except _FutTimeout:
            self._after_failure(key, phase)
            metrics.observe("broker_call_seconds", time.perf_counter() - t0, {"key": key, "result": "timeout"})
            raise TimeoutError(f"circuit call timed out for {key!r}")

    async def acall(
        self,
        key: str,
        afn: Callable[..., Any],
        *args: Any,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Async-вызов с опциональным timeout. Если цепь открыта — CircuitOpenError.
        """
        phase = self._before_call(key)
        if phase == "open":
            raise CircuitOpenError(f"circuit for {key!r} is open")

        t0 = time.perf_counter()
        try:
            if timeout is None:
                res = await afn(*args, **kwargs)
            else:
                res = await asyncio.wait_for(afn(*args, **kwargs), timeout=timeout)
            self._after_success(key, phase)
            metrics.observe("broker_call_seconds", time.perf_counter() - t0, {"key": key, "result": "ok"})
            return res
        except self.transient_exceptions as e:
            self._after_failure(key, phase)
            metrics.observe("broker_call_seconds", time.perf_counter() - t0, {"key": key, "result": "err"})
            raise
        except asyncio.TimeoutError:
            self._after_failure(key, phase)
            metrics.observe("broker_call_seconds", time.perf_counter() - t0, {"key": key, "result": "timeout"})
            raise TimeoutError(f"circuit call timed out for {key!r}")
