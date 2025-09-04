from __future__ import annotations

import os
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

_REGISTRY = CollectorRegistry()
_COUNTERS: dict[tuple[str, tuple[tuple[str, str], ...]], Counter] = {}
_GAUGES: dict[tuple[str, tuple[tuple[str, str], ...]], Gauge] = {}
_HISTS: dict[tuple[str, tuple[tuple[str, str], ...]], Histogram] = {}


def reset_registry() -> None:
    """Сброс реестра для тестов."""
    global _REGISTRY, _COUNTERS, _GAUGES, _HISTS
    _REGISTRY = CollectorRegistry()
    _COUNTERS = {}
    _GAUGES = {}
    _HISTS = {}


def _sanitize_name(name: str) -> str:
    """Convert dots and dashes to underscores for Prometheus compatibility."""
    return name.replace(".", "_").replace("-", "_")


def _key(name: str, labels: dict[str, str] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
    pairs = tuple(sorted((labels or {}).items()))
    return (name, pairs)


def _buckets_ms() -> tuple[float, ...]:
    env = os.environ.get("METRICS_BUCKETS_MS", "5,10,25,50,100,250,500,1000")
    try:
        vals = [float(x.strip()) for x in env.split(",") if x.strip()]
    except Exception:
        vals = [5, 10, 25, 50, 100, 250, 500, 1000]
    return tuple(v / 1000.0 for v in vals)


def inc(name: str, **labels: Any) -> None:
    """Counter +1"""
    name = _sanitize_name(name)
    labs = {k: str(v) for k, v in labels.items()}
    k = _key(name, labs)
    if k not in _COUNTERS:
        try:
            _COUNTERS[k] = Counter(name, name, list(labs.keys()), registry=_REGISTRY)
        except ValueError:
            # Метрика уже зарегистрирована, пытаемся найти существующую
            for metric in _REGISTRY.collect():
                if metric.name == name and isinstance(metric, Counter):
                    return
            return
    if k in _COUNTERS:
        _COUNTERS[k].labels(**labs).inc()


def gauge(name: str, **labels: Any) -> Gauge | None:
    """Gauge (вернёт объект, чтобы .set())"""
    name = _sanitize_name(name)
    labs = {k: str(v) for k, v in labels.items()}
    k = _key(name, labs)
    if k not in _GAUGES:
        try:
            _GAUGES[k] = Gauge(name, name, list(labs.keys()), registry=_REGISTRY)
        except ValueError:
            return None
    return _GAUGES[k].labels(**labs) if k in _GAUGES else None


def hist(name: str, **labels: Any) -> Histogram | None:
    """Histogram (секунды)"""
    name = _sanitize_name(name)
    labs = {k: str(v) for k, v in labels.items()}
    k = _key(name, labs)
    if k not in _HISTS:
        try:
            _HISTS[k] = Histogram(name, name, list(labs.keys()), buckets=_buckets_ms(), registry=_REGISTRY)
        except ValueError:
            return None
    return _HISTS[k].labels(**labs) if k in _HISTS else None


def observe(name: str, value: float, labels: dict[str, Any] | None = None) -> None:
    """Шорткaт для наблюдения значения (миллисекунды -> секунды)."""
    name = _sanitize_name(name)
    value_sec = float(value) / 1000.0
    h = hist(name, **(labels or {}))
    if h:
        h.observe(value_sec)


def export_text() -> str:
    """Для /metrics в FastAPI"""
    return generate_latest(_REGISTRY).decode("utf-8")
