from __future__ import annotations

import time
from collections import deque, defaultdict
from typing import Any, Callable, Dict, Deque, Optional

# простые метрики (наши)
from crypto_ai_bot.utils.metrics import inc, set_gauge


class CircuitBreaker:
    """
    Пер-ключевой circuit breaker с состояниями: closed -> half-open -> open.
    - fail_threshold: сколько подряд ошибок переводит в open
    - open_seconds: сколько держать open до перехода в half-open
    """

    def __init__(self) -> None:
        # state per key: "closed" | "open" | "half-open"
        self.state: Dict[str, str] = defaultdict(lambda: "closed")
        self.fail_count: Dict[str, int] = defaultdict(int)
        self.open_until: Dict[str, float] = {}
        self.last_errors: Dict[str, Deque[str]] = defaultdict(lambda: deque(maxlen=10))
        self.transitions_log: Deque[tuple[str, str, str, float]] = deque(maxlen=100)

    # ---- helpers

    @staticmethod
    def _state_to_value(s: str) -> float:
        # для gauge: closed=0, half-open=0.5, open=1
        return 0.0 if s == "closed" else (0.5 if s == "half-open" else 1.0)

    def _transition(self, key: str, new_state: str) -> None:
        old = self.state[key]
        if old != new_state:
            self.transitions_log.append((key, old, new_state, time.time()))
            self.state[key] = new_state
            # одна агрегированная метрика без лейблов (упрощаем экспорт)
            set_gauge("circuit_state", self._state_to_value(new_state))
            inc("broker_circuit_transitions_total", {"from": old, "to": new_state})

    # ---- public API

    def get_state(self, key: str) -> str:
        return self.state[key]

    def get_stats(self, key: str) -> dict:
        return {
            "state": self.state[key],
            "fail_count": self.fail_count.get(key, 0),
            "open_until": self.open_until.get(key),
            "last_errors": list(self.last_errors.get(key, [])),
            "transitions": [t for t in list(self.transitions_log)[-10:] if t[0] == key],
        }

    def record_error(self, key: str, err: Exception) -> None:
        self.last_errors[key].append(repr(err))

    def call(
        self,
        fn: Callable[[], Any],
        *,
        key: str,
        timeout: float,
        fail_threshold: int,
        open_seconds: float,
    ) -> Any:
        """
        Обёртка вызова: учитывает состояние, обновляет метрики/состояния.
        """
        now = time.time()
        st = self.state[key]

        # если open — проверяем таймер
        if st == "open":
            if now < self.open_until.get(key, 0.0):
                inc("broker_circuit_open_total")
                raise RuntimeError("circuit_open")
            # истёк таймер open → half-open
            self._transition(key, "half-open")
            st = "half-open"

        try:
            # сам вызов
            start = time.perf_counter()
            result = fn()
            elapsed = time.perf_counter() - start

            # успешный — сбрасываем счётчики и закрываем
            self.fail_count[key] = 0
            self._transition(key, "closed")
            inc("broker_requests_total", {"code": "200"})
            # грубая метрика длительности
            set_gauge("broker_last_call_seconds", float(elapsed))
            return result

        except Exception as exc:  # noqa: BLE001
            self.record_error(key, exc)
            self.fail_count[key] += 1
            inc("broker_errors_total", {"type": exc.__class__.__name__})

            # half-open → один фэйл = опять open
            if st in ("half-open", "closed") and self.fail_count[key] >= fail_threshold:
                self.open_until[key] = now + float(open_seconds)
                self._transition(key, "open")

            raise
