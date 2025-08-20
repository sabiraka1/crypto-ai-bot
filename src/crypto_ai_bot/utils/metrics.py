# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Optional

from prometheus_client import Counter, Histogram

# Глобальные реестры (простые и стабильные имена метрик)
_COUNTERS: Dict[str, Counter] = {}
_HIST: Dict[str, Histogram] = {}

def _labels(labels: Optional[Dict[str, str]]) -> Dict[str, str]:
    # Prometheus требует строковые метки
    if not labels:
        return {}
    return {str(k): str(v) for k, v in labels.items()}

def inc(name: str, labels: Optional[Dict[str, str]] = None, amount: float = 1.0) -> None:
    key = name
    if key not in _COUNTERS:
        _COUNTERS[key] = Counter(key, f"counter:{key}", labelnames=sorted(_labels(labels).keys()))
    c = _COUNTERS[key]
    if labels:
        c.labels(**_labels(labels)).inc(amount)
    else:
        c.inc(amount)

def observe_histogram(name: str, value: float, labels: Optional[Dict[str, str]] = None,
                      buckets: Optional[list[float]] = None) -> None:
    key = name
    if key not in _HIST:
        # разумные дефолтные бакеты, если не указаны
        b = buckets or [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
        _HIST[key] = Histogram(key, f"histogram:{key}", buckets=b, labelnames=sorted(_labels(labels).keys()))
    h = _HIST[key]
    if labels:
        h.labels(**_labels(labels)).observe(value)
    else:
        h.observe(value)

@contextmanager
def timer(name: str, labels: Optional[Dict[str, str]] = None):
    start = time.perf_counter()
    try:
        yield
    finally:
        observe_histogram(name, time.perf_counter() - start, labels=labels)
