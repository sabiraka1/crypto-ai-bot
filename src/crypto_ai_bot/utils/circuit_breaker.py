# src/crypto_ai_bot/utils/circuit_breaker.py
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Timeout
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional
from collections import deque

from crypto_ai_bot.utils import metrics


@dataclass
class _CBState:
    state: str = "closed"                 # closed | open | half-open
    failures: int = 0
    opened_at: float = 0.0                # when switched to open
    half_open_inflight: bool = False
    transitions: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=32))
    last_errors: Deque[str] = field(default_factory=lambda: deque(maxlen=16))


class CircuitBreaker:
    """
    Простой Circuit Breaker:
    - closed    → обычная работа
    - open      → все вызовы немедленно отклоняются до истечения open_seconds
    - half-open → одиночная проба; успех → closed, ошибка → open
    """

    def __init__(self) -> None:
        self._state: Dict[str, _CBState] = {}
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="cb")

    # ====== helpers ======
    def _get(self, key: str) -> _CBState:
        st = self._state.get(key)
        if st is None:
            st = _CBState()
            self._state[key] = st
        return st

    def _transition(self, key: str, new_state: str, reason: str) -> None:
        st = self._get(key)
        if st.state != new_state:
            st.transitions.append({
                "ts": time.time(),
                "from": st.state,
                "to": new_state,
                "reason": reason,
            })
            metrics.inc("circuit_transitions_total", {"key": key, "from": st.state, "to": new_state})
            st.state = new_state
            if new_state == "open":
                st.opened_at = time.time()
                st.half_open_inflight = False
            elif new_state == "closed":
                st.failures = 0
                st.half_open_inflight = False
            elif new_state == "half-open":
                st.half_open_inflight = False

    # ====== public API ======
    def call(
        self,
        fn: Callable[[], Any],
        *,
        key: str,
        timeout: float = 10.0,
        fail_threshold: int = 5,
        open_seconds: float = 30.0,
    ) -> Any:
        """
        Оборачивает вызов fn() политикой CB + таймаут через ThreadPool.
        """
        st = self._get(key)

        # OPEN → проверяем, можно ли в half-open
        if st.state == "open":
            if (time.time() - st.opened_at) >= open_seconds:
                self._transition(key, "half-open", "cooldown_elapsed")
            else:
                metrics.inc("circuit_blocked_total", {"key": key, "state": "open"})
                raise RuntimeError("circuit_open")

        # HALF-OPEN → пропускаем ровно одну пробу
        if st.state == "half-open":
            if st.half_open_inflight:
                metrics.inc("circuit_blocked_total", {"key": key, "state": "half-open"})
                raise RuntimeError("probe_inflight")
            st.half_open_inflight = True

        # Вызов с таймаутом
        fut = self._pool.submit(fn)
        try:
            res = fut.result(timeout=timeout)
        except _Timeout as e:
            fut.cancel()
            self._on_error(key, e, fail_threshold, open_seconds, err_tag="timeout")
            raise
        except Exception as e:
            self._on_error(key, e, fail_threshold, open_seconds, err_tag=type(e).__name__)
            raise

        # успех
        if st.state == "half-open":
            self._transition(key, "closed", "probe_success")
        else:
            # остаёмся closed
            st.failures = 0
        metrics.inc("circuit_calls_total", {"key": key, "result": "ok"})
        return res

    def _on_error(self, key: str, e: Exception, fail_threshold: int, open_seconds: float, err_tag: str) -> None:
        st = self._get(key)
        st.last_errors.append(f"{time.time():.3f}:{err_tag}:{repr(e)}")
        metrics.inc("circuit_calls_total", {"key": key, "result": "error", "type": err_tag})

        if st.state == "half-open":
            # проба провалилась → назад в open
            self._transition(key, "open", "probe_failed")
            return

        # closed: считаем фейлы
        st.failures += 1
        if st.failures >= fail_threshold:
            self._transition(key, "open", f"fail_threshold:{fail_threshold}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Возвращает агрегированные статистики по всем ключам.
        """
        now = time.time()
        out: Dict[str, Any] = {"keys": {}, "total": {"open": 0, "closed": 0, "half_open": 0}}
        for k, st in self._state.items():
            if st.state == "open":
                out["total"]["open"] += 1
            elif st.state == "closed":
                out["total"]["closed"] += 1
            else:
                out["total"]["half_open"] += 1

            out["keys"][k] = {
                "state": st.state,
                "failures": st.failures,
                "opened_for_sec": (now - st.opened_at) if st.opened_at else 0.0,
                "half_open_inflight": st.half_open_inflight,
                "transitions": list(st.transitions),
                "last_errors": list(st.last_errors),
            }
        return out
