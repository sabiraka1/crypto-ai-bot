## `utils/metrics.py`
from __future__ import annotations
from contextlib import contextmanager
from typing import Dict, Optional, Tuple
try:
    from prometheus_client import Counter, Histogram
except Exception:  # pragma: no cover - soft dependency fallback
    Counter = None  # type: ignore
    Histogram = None  # type: ignore
from .time import monotonic_ms
__all__ = [
    "inc",
    "observe",
    "timer",
]
_COUNTERS: Dict[Tuple[str, Tuple[str, ...]], object] = {}
_HISTOS: Dict[Tuple[str, Tuple[str, ...]], object] = {}
def _labels_tuple(labels: Optional[Dict[str, str]]) -> Tuple[str, ...]:
    if not labels:
        return tuple()
    return tuple(f"{k}={labels[k]}" for k in sorted(labels))
def inc(name: str, labels: Optional[Dict[str, str]] = None, amount: float = 1.0) -> None:
    """Increment a counter metric. No-op if prometheus_client is not installed."""
    key = (name, _labels_tuple(labels))
    if Counter is None:
        return  # graceful no-op
    if key not in _COUNTERS:
        label_keys = [kv.split("=", 1)[0] for kv in key[1]]
        _COUNTERS[key] = Counter(name, name, labelkeys=label_keys)  # type: ignore[arg-type]
    c = _COUNTERS[key]
    if labels:
        c.labels(**{k: v for k, v in (kv.split("=", 1) for kv in key[1])}).inc(amount)  # type: ignore[attr-defined]
    else:
        c.inc(amount)  # type: ignore[attr-defined]
def observe(name: str, value: float, labels: Optional[Dict[str, str]] = None, buckets: Optional[Tuple[float, ...]] = None) -> None:
    """Observe a value in a histogram metric. No-op if prometheus_client is missing."""
    key = (name, _labels_tuple(labels))
    if Histogram is None:
        return
    if key not in _HISTOS:
        label_keys = [kv.split("=", 1)[0] for kv in key[1]]
        if buckets:
            _HISTOS[key] = Histogram(name, name, labelkeys=label_keys, buckets=buckets)  # type: ignore[arg-type]
        else:
            _HISTOS[key] = Histogram(name, name, labelkeys=label_keys)  # type: ignore[arg-type]
    h = _HISTOS[key]
    if labels:
        h.labels(**{k: v for k, v in (kv.split("=", 1) for kv in key[1])}).observe(value)  # type: ignore[attr-defined]
    else:
        h.observe(value)  # type: ignore[attr-defined]
@contextmanager
def timer(name: str, labels: Optional[Dict[str, str]] = None):
    """Context manager that measures elapsed time (ms) and observes it in a histogram."""
    start = monotonic_ms()
    try:
        yield
    finally:
        dur_ms = monotonic_ms() - start
        observe(name, dur_ms, labels)
