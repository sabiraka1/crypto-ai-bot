from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, generate_latest

_REGISTRY = CollectorRegistry()
_COUNTERS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Counter] = {}
_GAUGES: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Gauge] = {}
_HISTS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Histogram] = {}

def _key(name: str, labels: Dict[str, str] | None) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
    pairs = tuple(sorted((labels or {}).items()))
    return (name, pairs)

def _buckets_ms() -> Tuple[float, ...]:
    env = os.environ.get("METRICS_BUCKETS_MS", "5,10,25,50,100,250,500,1000")
    try:
        vals = [float(x.strip()) for x in env.split(",") if x.strip()]
    except Exception:
        vals = [5, 10, 25, 50, 100, 250, 500, 1000]
    # гистограмма в секундах
    return tuple(v / 1000.0 for v in vals)

def inc(name: str, **labels: Any) -> None:
    """Counter +1"""
    labs = {k: str(v) for k, v in labels.items()}
    k = _key(name, labs)
    if k not in _COUNTERS:
        _COUNTERS[k] = Counter(name, name, list(dict(k[1]).keys()), registry=_REGISTRY)
    _COUNTERS[k].labels(**dict(k[1])).inc()

def gauge(name: str, **labels: Any) -> Gauge:
    """Gauge (вернёт объект, чтобы .set())"""
    labs = {k: str(v) for k, v in labels.items()}
    k = _key(name, labs)
    if k not in _GAUGES:
        _GAUGES[k] = Gauge(name, name, list(dict(k[1]).keys()), registry=_REGISTRY)
    return _GAUGES[k].labels(**dict(k[1]))

def hist(name: str, **labels: Any) -> Histogram:
    """Histogram (секунды)"""
    labs = {k: str(v) for k, v in labels.items()}
    k = _key(name, labs)
    if k not in _HISTS:
        _HISTS[k] = Histogram(name, name, list(dict(k[1]).keys()), buckets=_buckets_ms(), registry=_REGISTRY)
    return _HISTS[k].labels(**dict(k[1]))

def observe(name: str, value: float, labels: dict[str, str] | None = None) -> None:
    """Шорткат для наблюдения значения (секунды)"""
    (hist(name, **(labels or {}))).observe(float(value))

def export_text() -> str:
    """Для /metrics в FastAPI"""
    return generate_latest(_REGISTRY).decode("utf-8")
