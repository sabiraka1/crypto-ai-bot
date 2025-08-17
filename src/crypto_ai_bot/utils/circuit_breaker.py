# src/crypto_ai_bot/utils/circuit_breaker.py
from __future__ import annotations
import time
import threading
from typing import Any, Callable, Dict, Optional, Tuple, List


class CircuitBreaker:
    """
    Простая реализация Circuit Breaker со статусами:
      - closed     : вызовы проходят, считаем фейлы
      - open       : вызовы блокируются на open_seconds
      - half-open  : пробная попытка; успех -> closed, фейл -> open

    Совместима с существующим вызовом:
      breaker.call(fn, *, key="broker.fetch_ticker", timeout=2.0, fail_threshold=3, open_seconds=30, ...)
    """

    def __init__(self, default_fail_threshold: int = 3, default_open_seconds: float = 30.0):
        self._lock = threading.Lock()
        self._state: Dict[str, Dict[str, Any]] = {}
        self._default_fail_threshold = default_fail_threshold
        self._default_open_seconds = default_open_seconds
        # агрегированные метрики
        self._counters: Dict[str, Dict[str, int]] = {}  # per key: attempts/successes/failures/opens/half_opens
        # краткий лог переходов (per key)
        self._transitions: Dict[str, List[Tuple[float, str, str]]] = {}  # (ts, from, to)
        # последние ошибки
        self._last_errors: Dict[str, str] = {}

    # ---------- внутренние помощники ----------
    def _now(self) -> float:
        return time.time()

    def _ensure_key(self, key: str) -> None:
        if key not in self._state:
            self._state[key] = {
                "state": "closed",
                "failures": 0,
                "opened_at": None,          # float|None
                "last_transition": self._now(),
                "fail_threshold": self._default_fail_threshold,
                "open_seconds": self._default_open_seconds,
            }
            self._counters[key] = {"attempts": 0, "successes": 0, "failures": 0, "opens": 0, "half_opens": 0}
            self._transitions[key] = []

    def _transition(self, key: str, to_state: str) -> None:
        st = self._state[key]
        frm = st["state"]
        if frm == to_state:
            return
        st["state"] = to_state
        st["last_transition"] = self._now()
        if to_state == "open":
            st["opened_at"] = self._now()
            self._counters[key]["opens"] += 1
        elif to_state == "half-open":
            self._counters[key]["half_opens"] += 1
        # лог переходов (держим компактно)
        log = self._transitions[key]
        log.append((self._now(), frm, to_state))
        if len(log) > 32:
            del log[: len(log) - 32]

    # ---------- публичное API ----------
    def get_stats(self) -> Dict[str, Any]:
        """Снимок состояния по всем ключам для health/details и метрик."""
        with self._lock:
            out = {}
            for key, st in self._state.items():
                out[key] = {
                    "state": st["state"],
                    "failures": st["failures"],
                    "fail_threshold": st["fail_threshold"],
                    "open_seconds": st["open_seconds"],
                    "opened_at": st["opened_at"],
                    "last_transition": st["last_transition"],
                    "counters": dict(self._counters.get(key, {})),
                    "last_error": self._last_errors.get(key),
                    "transitions": list(self._transitions.get(key, [])),
                }
            return out

    def call(
        self,
        fn: Callable[..., Any],
        *,
        key: str,
        timeout: Optional[float] = None,
        fail_threshold: Optional[int] = None,
        open_seconds: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Выполняет вызов под контролем предохранителя.
        - Если breaker открыт и время не истекло — бросит RuntimeError (или вернёт fallback, если передан через kwargs).
        - Поддерживает кастомные пороги per-call через параметры.

        Пример:
            breaker.call(client.fetch_ticker, key="broker.fetch_ticker", timeout=2.0)
        """
        fallback = kwargs.pop("fallback", None)

        with self._lock:
            self._ensure_key(key)
            st = self._state[key]
            if fail_threshold is not None:
                st["fail_threshold"] = int(fail_threshold)
            if open_seconds is not None:
                st["open_seconds"] = float(open_seconds)

            state = st["state"]

            # Если открыт — проверяем, не истёк ли таймер
            if state == "open":
                opened_at = st["opened_at"] or 0.0
                if self._now() - opened_at < st["open_seconds"]:
                    # ещё открыт
                    if fallback is not None:
                        return fallback()
                    raise RuntimeError("circuit_open")
                else:
                    # пробуем half-open
                    self._transition(key, "half-open")

            self._counters[key]["attempts"] += 1

        # Вызов без блокировки
        err: Optional[BaseException] = None
        result: Any = None
        try:
            if timeout is not None:
                # простая обёртка таймаута: для sync-IO делаем мягкий подход
                # (ожидание таймаута как часть операции — реальный таймаут должен быть в клиенте)
                result = fn(**kwargs)
            else:
                result = fn(**kwargs)

        except BaseException as e:
            err = e

        with self._lock:
            self._ensure_key(key)
            st = self._state[key]

            if err is None:
                # успех
                st["failures"] = 0
                if st["state"] in ("half-open", "open"):
                    self._transition(key, "closed")
                self._counters[key]["successes"] += 1
                return result

            # ошибка
            self._counters[key]["failures"] += 1
            self._last_errors[key] = f"{type(err).__name__}: {err}"

            st["failures"] += 1
            if st["state"] == "half-open":
                # неудачная проба — обратно в open
                self._transition(key, "open")
            else:
                # closed: проверяем порог
                if st["failures"] >= st["fail_threshold"]:
                    self._transition(key, "open")

        # если есть fallback — используем
        if fallback is not None:
            return fallback()

        raise err  # пробрасываем оригинальную ошибку
