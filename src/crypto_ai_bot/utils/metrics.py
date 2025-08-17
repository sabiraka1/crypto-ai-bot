from __future__ import annotations

import time
import threading
from contextlib import contextmanager
from typing import Dict, Tuple, Iterable, Optional, List

try:
    from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
except Exception:
    # Позволяет работать даже без установленного prometheus_client (например, в unit-тестах),
    # но в проде библиотека должна быть установлена.
    Counter = Gauge = Histogram = object  # type: ignore
    class CollectorRegistry: ...
    def generate_latest(*_a, **_k): return b""
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

_registry = CollectorRegistry() if isinstance(CollectorRegistry, type) else None  # type: ignore

_COUNTERS: Dict[str, Counter] = {}
_GAUGES: Dict[str, Gauge] = {}
_HISTS: Dict[str, Histogram] = {}

# Локальные резервуары последних значений для расчёта p95/p99 на /status/extended
# (promql-квантили всё равно будут в Prometheus, но нам нужен быстрый «снимок» в API)
_RESERVOIRS: Dict[str, List[float]] = {}
_RESERVOIR_MAX = 2000  # кольцевой буфер

_LOCK = threading.RLock()

# --- Бакеты по умолчанию ---
# Латентности (сек): 5ms..5s
_DEFAULT_LAT_BUCKETS = (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0)
# Скор (0..1)
_DEFAULT_SCORE_BUCKETS = tuple(round(x / 100, 3) for x in range(0, 101, 5))  # 0.00,0.05,...,1.00

# Явные профили бакетов по имени метрики (при необходимости можно дополнять)
_BUCKETS_MAP: Dict[str, Tuple[float, ...]] = {
    "latency_decide_seconds": _DEFAULT_LAT_BUCKETS,
    "latency_order_seconds": _DEFAULT_LAT_BUCKETS,
    "decision_score_histogram": _DEFAULT_SCORE_BUCKETS,
}

# --- Ленивая регистрация метрик ---
def _counter(name: str, help_: str = "", labels: Iterable[str] = ()) -> Counter:
    with _LOCK:
        if name not in _COUNTERS:
            if _registry is not None and isinstance(Counter, type):
                _COUNTERS[name] = Counter(name, help_ or name, list(labels), registry=_registry)  # type: ignore
            else:
                _COUNTERS[name] = None  # type: ignore
        return _COUNTERS[name]

def _gauge(name: str, help_: str = "", labels: Iterable[str] = ()) -> Gauge:
    with _LOCK:
        if name not in _GAUGES:
            if _registry is not None and isinstance(Gauge, type):
                _GAUGES[name] = Gauge(name, help_ or name, list(labels), registry=_registry)  # type: ignore
            else:
                _GAUGES[name] = None  # type: ignore
        return _GAUGES[name]

def _hist(name: str, help_: str = "", buckets: Optional[Tuple[float, ...]] = None, labels: Iterable[str] = ()) -> Histogram:
    with _LOCK:
        if name not in _HISTS:
            if buckets is None:
                buckets = _BUCKETS_MAP.get(name)
            if buckets is None:
                # Фолбэк: латентности
                buckets = _DEFAULT_LAT_BUCKETS
            if _registry is not None and isinstance(Histogram, type):
                _HISTS[name] = Histogram(name, help_ or name, list(labels), buckets=buckets, registry=_registry)  # type: ignore
            else:
                _HISTS[name] = None  # type: ignore
        return _HISTS[name]

# --- Публичное API (совместимое с существующим кодом) ---

def inc(name: str, labels: Optional[Dict[str, str]] = None, *, help_: str = "") -> None:
    c = _counter(name, help_, labels.keys() if labels else ())
    if c is None:
        return
    if labels:
        c.labels(**labels).inc()  # type: ignore[attr-defined]
    else:
        c.inc()  # type: ignore[attr-defined]

def set(name: str, value: float, labels: Optional[Dict[str, str]] = None, *, help_: str = "") -> None:
    g = _gauge(name, help_, labels.keys() if labels else ())
    if g is None:
        return
    if labels:
        g.labels(**labels).set(value)  # type: ignore[attr-defined]
    else:
        g.set(value)  # type: ignore[attr-defined]

def observe_histogram(name: str, value: float, labels: Optional[Dict[str, str]] = None, *,
                      help_: str = "", buckets: Optional[Tuple[float, ...]] = None) -> None:
    """Единая точка наблюдения гистограмм (убираем дубли _observe_hist в коде)."""
    h = _hist(name, help_, buckets, labels.keys() if labels else ())
    if h is not None:
        if labels:
            h.labels(**labels).observe(value)  # type: ignore[attr-defined]
        else:
            h.observe(value)  # type: ignore[attr-defined]
    # Параллельно пополняем локальный резервуар для быстрых квантилий на /status/extended
    with _LOCK:
        arr = _RESERVOIRS.setdefault(name, [])
        arr.append(float(value))
        if len(arr) > _RESERVOIR_MAX:
            del arr[: len(arr) - _RESERVOIR_MAX]

@contextmanager
def timer():
    """Контекст-таймер: with timer() as t: ...; t.elapsed"""
    start = time.perf_counter()
    obj = type("T", (), {})()
    obj.elapsed = 0.0
    try:
        yield obj
    finally:
        obj.elapsed = float(time.perf_counter() - start)

def quantiles(name: str, probs: Iterable[float]) -> Dict[float, Optional[float]]:
    """p95/p99 «на лету» из локального резервуара (для /status/extended).
    Для точной аналитики использовать Prometheus (histogram_quantile)."""
    with _LOCK:
        data = list(_RESERVOIRS.get(name, []))
    if not data:
        return {p: None for p in probs}
    data.sort()
    out: Dict[float, Optional[float]] = {}
    n = len(data)
    for p in probs:
        if not 0.0 <= p <= 1.0:
            out[p] = None
            continue
        k = max(0, min(n - 1, int(round((n - 1) * p))))
        out[p] = float(data[k])
    return out

def check_performance_budget(metric: str, value_seconds: float, budget_seconds: Optional[float]) -> None:
    """Если есть бюджет и он превышен — инкрементируем performance_budget_exceeded и логируем предупреждение."""
    if budget_seconds is None:
        return
    if value_seconds > float(budget_seconds):
        inc("performance_budget_exceeded", {"metric": metric})
        # Логгер не подключаем здесь напрямую, чтобы не плодить зависимостей; логи — на уровне вызова.

def export_prometheus() -> Tuple[bytes, str]:
    """Отдаёт срез метрик для /metrics."""
    if _registry is None:
        return b"", CONTENT_TYPE_LATEST
    return generate_latest(_registry), CONTENT_TYPE_LATEST
