# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations

from typing import Dict, Optional
from prometheus_client import Counter, Histogram, Gauge

# Примеры реестров метрик (вы свои уже используете — оставляю совместимую форму)
_METRIC_COUNTERS: Dict[str, Counter] = {}
_METRIC_HISTOS: Dict[str, Histogram] = {}
_METRIC_GAUGES: Dict[str, Gauge] = {}

def _labels(labels: Optional[dict] = None) -> dict[str, str]:
    if not labels:
        return {}
    # Жёстко приводим к str:str и игнорируем нестандарт
    out: dict[str, str] = {}
    for k, v in labels.items():
        out[str(k)] = str(v)
    return out

def inc(name: str, labels: Optional[dict] = None, doc: str = "counter") -> None:
    if name not in _METRIC_COUNTERS:
        _METRIC_COUNTERS[name] = Counter(name, doc, list((_labels(labels) or {}).keys()))
    c = _METRIC_COUNTERS[name]
    if labels:
        c.labels(**_labels(labels)).inc()
    else:
        c.inc()

def observe_histogram(name: str, value: float, labels: Optional[dict] = None,
                      buckets: Optional[list[float]] = None,
                      doc: str = "histogram") -> None:
    if name not in _METRIC_HISTOS:
        _METRIC_HISTOS[name] = Histogram(name, doc, list((_labels(labels) or {}).keys()),
                                         buckets=buckets) if buckets else Histogram(name, doc, list((_labels(labels) or {}).keys()))
    h = _METRIC_HISTOS[name]
    if labels:
        h.labels(**_labels(labels)).observe(value)
    else:
        h.observe(value)

def observe_gauge(name: str, value: float, labels: Optional[dict] = None,
                  doc: str = "gauge") -> None:
    if name not in _METRIC_GAUGES:
        _METRIC_GAUGES[name] = Gauge(name, doc, list((_labels(labels) or {}).keys()))
    g = _METRIC_GAUGES[name]
    if labels:
        g.labels(**_labels(labels)).set(value)
    else:
        g.set(value)
