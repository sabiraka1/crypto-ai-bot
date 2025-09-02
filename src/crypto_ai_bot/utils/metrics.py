from __future__ import annotations

import os
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

_REGISTRY = CollectorRegistry()
_COUNTERS: dict[tuple[str, tuple[tuple[str, str], ...]], Counter] = {}
_GAUGES: dict[tuple[str, tuple[tuple[str, str], ...]], Gauge] = {}
_HISTS: dict[tuple[str, tuple[tuple[str, str], ...]], Histogram] = {}

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
    # гистограмма в секундах
    return tuple(v / 1000.0 for v in vals)

def inc(name: str, **labels: Any) -> None:
    """Counter +1"""
    name = _sanitize_name(name)  # Санитизация имени
    labs = {k: str(v) for k, v in labels.items()}
    k = _key(name, labs)
    if k not in _COUNTERS:
        _COUNTERS[k] = Counter(name, name, list(dict(k[1]).keys()), registry=_REGISTRY)
    _COUNTERS[k].labels(**dict(k[1])).inc()

def gauge(name: str, **labels: Any) -> Gauge:
    """Gauge (вернёт объект, чтобы .set())"""
    name = _sanitize_name(name)  # Санитизация имени
    labs = {k: str(v) for k, v in labels.items()}
    k = _key(name, labs)
    if k not in _GAUGES:
        _GAUGES[k] = Gauge(name, name, list(dict(k[1]).keys()), registry=_REGISTRY)
    return _GAUGES[k].labels(**dict(k[1]))

def hist(name: str, **labels: Any) -> Histogram:
    """Histogram (секунды)"""
    name = _sanitize_name(name)  # Санитизация имени
    labs = {k: str(v) for k, v in labels.items()}
    k = _key(name, labs)
    if k not in _HISTS:
        _HISTS[k] = Histogram(name, name, list(dict(k[1]).keys()), buckets=_buckets_ms(), registry=_REGISTRY)
    return _HISTS[k].labels(**dict(k[1]))

def observe(name: str, value: float, labels: dict[str, str] | None = None) -> None:
    """Шорткат для наблюдения значения (секунды)"""
    name = _sanitize_name(name)  # Санитизация имени
    (hist(name, **(labels or {}))).observe(float(value))

def export_text() -> str:
    """Для /metrics в FastAPI"""
    return generate_latest(_REGISTRY).decode("utf-8")