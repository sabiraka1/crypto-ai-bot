# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

try:
    # предпочитаем официальный клиент
    from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram, generate_latest  # type: ignore
    _PROM = True
except Exception:  # pragma: no cover
    _PROM = False
    REGISTRY = None  # type: ignore

# ---------- внутренние реестры ----------

_counters: Dict[str, Any] = {}
_gauges: Dict[str, Any] = {}
_hists: Dict[str, Any] = {}

# Бакеты: секунды (под сервера/HTTP/брокер), с плавной «верхушкой»
_DEFAULT_BUCKETS = (
    0.005, 0.01, 0.025, 0.05, 0.075,
    0.1, 0.2, 0.3, 0.5,
    0.75, 1.0, 1.5, 2.0, 3.0,
    5.0, 7.5, 10.0, float("inf")
)

def _labels_sorted(labels: Dict[str, str]) -> Dict[str, str]:
    # стабилизируем порядок лейблов, чтобы не плодить уникальные серии
    return dict(sorted((labels or {}).items()))

def _norm_name(name: str) -> str:
    # простая нормализация
    return name.replace(".", "_").replace("-", "_").strip()

# ---------- публичное API ----------

def inc(name: str, labels: Optional[Dict[str, str]] = None, *, value: float = 1.0) -> None:
    n = _norm_name(name)
    if _PROM:
        key = (n, tuple(sorted((labels or {}).items())))
        if key not in _counters:
            _counters[key] = Counter(n, n, list((labels or {}).keys()))
        _counters[key].labels(**_labels_sorted(labels or {})).inc(value)
    else:  # no-op fallback
        pass

def gauge(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    n = _norm_name(name)
    if _PROM:
        key = (n, tuple(sorted((labels or {}).items())))
        if key not in _gauges:
            _gauges[key] = Gauge(n, n, list((labels or {}).keys()))
        _gauges[key].labels(**_labels_sorted(labels or {})).set(value)
    else:
        pass

def set(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    # алиас для gauge
    gauge(name, value, labels)

def observe_histogram(name: str, value_seconds: float, labels: Optional[Dict[str, str]] = None, *, buckets: Optional[tuple] = None) -> None:
    n = _norm_name(name)
    if _PROM:
        key = (n, tuple(sorted((labels or {}).items())))
        if key not in _hists:
            _hists[key] = Histogram(n, n, list((labels or {}).keys()), buckets=buckets or _DEFAULT_BUCKETS)
        _hists[key].labels(**_labels_sorted(labels or {})).observe(float(value_seconds))
    else:
        pass

@contextmanager
def timer():
    t0 = time.time()
    class _T:
        elapsed: float = 0.0
    T = _T()
    try:
        yield T
    finally:
        T.elapsed = max(0.0, time.time() - t0)

def export() -> str:
    """Совместимость: вернём Prometheus-текст (или пустую строку, если клиента нет)."""
    if not _PROM:
        return ""
    try:
        body = generate_latest()  # bytes
        return body.decode("utf-8", errors="ignore")
    except Exception:
        return ""

# Дополнительно: бюджет (сейчас почти не используется; оставляем для обратной совместимости)
def check_performance_budget(metric_key: str, value_seconds: float, budget_seconds: Optional[float]) -> None:
    try:
        if budget_seconds and value_seconds > float(budget_seconds):
            gauge("performance_budget_exceeded_local", 1.0, {"type": metric_key})
        else:
            if budget_seconds:
                gauge("performance_budget_exceeded_local", 0.0, {"type": metric_key})
    except Exception:
        pass
