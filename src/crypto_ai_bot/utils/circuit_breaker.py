# src/crypto_ai_bot/utils/circuit_breaker.py
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

try:
    # метрики опциональны — не рушим импорт, если их нет
    from . import metrics  # type: ignore
except Exception:  # pragma: no cover
    class _Dummy:
        def inc(self, *a, **k): ...
        def observe(self, *a, **k): ...
        def export(self) -> str: return ""
    metrics = _Dummy()  # type: ignore


@dataclass
class _State:
    state: str = "closed"          # closed | open | half-open
    failures: int = 0
    opened_at: float = 0.0         # when transitioned to open
    half_open_probe: bool = False  # единственный пробный вызов в half-open


class CircuitOpenError(RuntimeError):
    """Поднимается, когда предохранитель в состоянии OPEN и окно ещё не истекло."""


class CircuitBreaker:
    """
    Устойчивый к ошибочным вызовам интерфейс (поддерживает и *args, и **kwargs).
    Контракты:
      - call(fn, key=..., timeout=?, fail_threshold=?, open_seconds=?, args=(), kwargs={})
      - call(fn, "key", timeout=?, ...)
      - call(fn, key="key")     # классическая форма
    Любые дублирующиеся 'key' корректно разбираются (берём именованный приоритетно).
    """

    def __init__(
        self,
        *,
        default_fail_threshold: int = 3,
        default_open_seconds: float = 30.0,
        default_timeout: Optional[float] = None,  # тут не применяем, таймаут должен быть в самом fn
    ) -> None:
        self._lock = threading.RLock()
        self._states: Dict[str, _State] = {}
        self._def_fail_threshold = int(default_fail_threshold)
        self._def_open_seconds = float(default_open_seconds)
        self._def_timeout = default_timeout

    # --------- API ---------
    def get_state(self, key: str) -> str:
        with self._lock:
            st = self._states.get(key)
            return st.state if st else "closed"

    def call(self, *args, **kwargs) -> Any:
        """
        Универсальный вызов с защитой.
        Поддерживает ошибочные формы вида: call(fn, "key", key="key", ...)
        — мы не падаем, а просто выбираем именованный 'key'.
        """
        if not args and "fn" not in kwargs:
            raise TypeError("CircuitBreaker.call(...) requires at least a callable 'fn'")

        # ---- извлекаем fn ----
        fn: Callable[..., Any] | None = kwargs.pop("fn", None)
        if fn is None:
            fn = args[0]  # type: ignore[assignment]
            args = args[1:]
        if not callable(fn):
            raise TypeError("first argument to CircuitBreaker.call must be callable")

        # ---- извлекаем key ----
        key_kw = kwargs.pop("key", None)
        key_pos = None
        if args:
            # если пользователи передали позиционный 'key'
            key_pos = args[0]
            args = args[1:]

        key = key_kw if key_kw is not None else key_pos
        if key is None:
            key = getattr(fn, "__name__", "anonymous")
        key = str(key)

        # Параметры с дефолтами: сейчас они логически не влияют на выполнение,
        # но сохраняем для совместимости сигнатуры.
        fail_threshold = int(kwargs.pop("fail_threshold", self._def_fail_threshold))
        open_seconds = float(kwargs.pop("open_seconds", self._def_open_seconds))
        # timeout оставляем пользователю — fn должен сам уметь таймаутиться
        _ = kwargs.pop("timeout", self._def_timeout)

        # Любые оставшиеся kwargs считаем параметрами для fn
        fn_kwargs = kwargs.copy()
        fn_args = args

        # ---- логика состояний ----
        with self._lock:
            st = self._states.setdefault(key, _State())
            now = time.monotonic()

            if st.state == "open":
                if now - st.opened_at < open_seconds:
                    # окно ещё не истекло — немедленно отдаем ошибку (транзиентную)
                    metrics.inc("broker_circuit_reject_total", {"key": key})
                    raise CircuitOpenError(f"circuit_open:{key}")
                # истекло окно — переходим в half-open и разрешаем один пробный вызов
                st.state = "half-open"
                st.half_open_probe = False
                st.failures = 0

            if st.state == "half-open":
                # допускаем только один пробный вызов; остальные — отклоняем
                if st.half_open_probe:
                    metrics.inc("broker_circuit_reject_total", {"key": key})
                    raise CircuitOpenError(f"circuit_half_open_pending:{key}")
                st.half_open_probe = True

        # ---- выполнение fn вне блокировки ----
        try:
            res = fn(*fn_args, **fn_kwargs)
        except Exception as e:
            with self._lock:
                st = self._states[key]
                st.failures += 1
                if st.state in ("closed", "half-open") and st.failures >= fail_threshold:
                    st.state = "open"
                    st.opened_at = time.monotonic()
                    st.half_open_probe = False
                    metrics.inc("broker_circuit_open_total", {"key": key})
            raise
        else:
            with self._lock:
                st = self._states[key]
                # успешный вызов всегда закрывает предохранитель
                st.state = "closed"
                st.failures = 0
                st.half_open_probe = False
            return res

    # Удобный декоратор — OPTIONAL
    def wrap(self, key: str):
        def _decor(f: Callable[..., Any]):
            def _inner(*a, **k):
                return self.call(f, key, *a, **k)
            return _inner
        return _decor


# Глобальный экземпляр на весь процесс — удобно для простого использования
_default_cb = CircuitBreaker()


def get_breaker() -> CircuitBreaker:
    return _default_cb
