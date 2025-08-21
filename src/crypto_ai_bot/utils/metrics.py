from __future__ import annotations
import time
from contextlib import contextmanager
from typing import Dict, Optional, Tuple

try:
    from prometheus_client import Counter, Histogram  # type: ignore
except Exception:  # модуль может отсутствовать
    Counter = None  # type: ignore
    Histogram = None  # type: ignore

# Кэш по (name, labelnames_tuple_sorted) -> Metric
_COUNTERS: Dict[Tuple[str, Tuple[str, ...]], object] = {}
_HISTS: Dict[Tuple[str, Tuple[str, ...]], object] = {}

def _labels_tuple(labels: Optional[Dict[str, str]]) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return tuple()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

def _labelnames(labels: Optional[Dict[str, str]]) -> Tuple[str, ...]:
    if not labels:
        return tuple()
    return tuple(sorted(str(k) for k in labels))

def inc(name: str, labels: Optional[Dict[str, str]] = None, amount: float = 1.0) -> None:
    if Counter is None:
        return
    ln = _labelnames(labels)
    key = (name, ln)
    if key not in _COUNTERS:
        _COUNTERS[key] = Counter(name, name, labelnames=list(ln))  # type: ignore[arg-type]
    c = _COUNTERS[key]
    if ln:
        c.labels(*[labels[k] for k in ln]).inc(amount)  # type: ignore[call-arg]
    else:
        c.inc(amount)  # type: ignore[call-arg]

def observe(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    if Histogram is None:
        return
    ln = _labelnames(labels)
    key = (name, ln)
    if key not in _HISTS:
        _HISTS[key] = Histogram(name, name, labelnames=list(ln))  # type: ignore[arg-type]
    h = _HISTS[key]
    if ln:
        h.labels(*[labels[k] for k in ln]).observe(value)  # type: ignore[call-arg]
    else:
        h.observe(value)  # type: ignore[call-arg]

@contextmanager
def timer(name: str, labels: Optional[Dict[str, str]] = None):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        observe(name, dt, labels=labels)
