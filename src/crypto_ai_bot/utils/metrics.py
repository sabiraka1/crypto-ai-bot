# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations
from typing import Dict, Iterable, Optional, Tuple

try:
    from prometheus_client import Counter, Gauge, Histogram
    PROM = True
except Exception:
    PROM = False

_REG_C: Dict[str, object] = {}
_REG_G: Dict[str, object] = {}
_REG_H: Dict[str, object] = {}

def _labels(labels: Optional[Dict[str, str]]) -> Dict[str, str]:
    if not labels:
        return {}
    # force str->str for Prom
    return {str(k): str(v) for k, v in labels.items()}

def inc(name: str, labels: Optional[Dict[str, str]] = None, help: str = "") -> None:
    if not PROM:
        return
    key = (name, tuple(sorted((labels or {}).items())))
    if name not in _REG_C:
        _REG_C[name] = Counter(name, help or name, list((labels or {}).keys()))
    c: Counter = _REG_C[name]  # type: ignore
    c.labels(**_labels(labels)).inc()

def set_gauge(name: str, value: float, labels: Optional[Dict[str, str]] = None, help: str = "") -> None:
    if not PROM:
        return
    if name not in _REG_G:
        _REG_G[name] = Gauge(name, help or name, list((labels or {}).keys()))
    g: Gauge = _REG_G[name]  # type: ignore
    g.labels(**_labels(labels)).set(value)

def observe_histogram(
    name: str,
    value: float,
    labels: Optional[Dict[str, str]] = None,
    buckets: Optional[Iterable[float]] = None,
    help: str = "",
) -> None:
    if not PROM:
        return
    if name not in _REG_H:
        if buckets is None:
            _REG_H[name] = Histogram(name, help or name, list((labels or {}).keys()))
        else:
            _REG_H[name] = Histogram(name, help or name, list((labels or {}).keys()), buckets=buckets)
    h: Histogram = _REG_H[name]  # type: ignore
    h.labels(**_labels(labels)).observe(value)
