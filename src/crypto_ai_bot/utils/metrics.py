# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from prometheus_client import Counter, Gauge, Histogram, Summary

# Кэш уже созданных метрик, чтобы не плодить дубликаты
_COUNTERS: Dict[Tuple[str, Tuple[str, ...]], Counter] = {}
_GAUGES: Dict[Tuple[str, Tuple[str, ...]], Gauge] = {}
_HISTOGRAMS: Dict[Tuple[str, Tuple[str, ...]], Histogram] = {}
_SUMMARIES: Dict[Tuple[str, Tuple[str, ...]], Summary] = {}

# Разрешённые символы в метках Prometheus (остальное заменяем на '_')
_SANITIZE = re.compile(r"[^a-zA-Z0-9:_]")


def _labels_tuple(labels: Optional[Dict[str, str]]) -> Tuple[str, ...]:
    if not labels:
        return tuple()
    return tuple(sorted(labels.keys()))


def _sanitize_labels(labels: Optional[Dict[str, object]]) -> Dict[str, str]:
    if not labels:
        return {}
    safe: Dict[str, str] = {}
    for k, v in labels.items():
        ks = _SANITIZE.sub("_", str(k))[:100]
        vs = _SANITIZE.sub("_", str(v))[:200]
        safe[ks] = vs
    return safe


def inc(name: str, labels: Optional[Dict[str, object]] = None, amount: float = 1.0) -> None:
    """
    Счётчик +1 (по умолчанию). Пример:
      inc("orders_attempt_total", {"symbol": "BTC_USDT", "side": "buy"})
    """
    lspec = _labels_tuple({} if labels is None else {str(k): "" for k in labels.keys()})
    key = (name, lspec)
    if key not in _COUNTERS:
        _COUNTERS[key] = Counter(name, name, list(lspec))
    _COUNTERS[key].labels(**_sanitize_labels(labels)).inc(amount)


def set_gauge(name: str, value: float, labels: Optional[Dict[str, object]] = None) -> None:
    """
    Установить значение gauge. Пример:
      set_gauge("exchange_latency_seconds", 0.123, {"exchange": "gateio"})
    """
    lspec = _labels_tuple({} if labels is None else {str(k): "" for k in labels.keys()})
    key = (name, lspec)
    if key not in _GAUGES:
        _GAUGES[key] = Gauge(name, name, list(lspec))
    _GAUGES[key].labels(**_sanitize_labels(labels)).set(float(value))


def observe_histogram(
    name: str,
    value: float,
    labels: Optional[Dict[str, object]] = None,
    buckets: Optional[Tuple[float, ...]] = None,
) -> None:
    """
    Наблюдение для гистограммы. По умолчанию — «latency-подобные» buckets.
    """
    lspec = _labels_tuple({} if labels is None else {str(k): "" for k in labels.keys()})
    key = (name, lspec)
    if key not in _HISTOGRAMS:
        if buckets is None:
            buckets = (0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0)
        _HISTOGRAMS[key] = Histogram(name, name, list(lspec), buckets=buckets)
    _HISTOGRAMS[key].labels(**_sanitize_labels(labels)).observe(float(value))


def observe_summary(name: str, value: float, labels: Optional[Dict[str, object]] = None) -> None:
    """
    Наблюдение для summary (P50/P90/P99). Используйте, если вашим значениям
    не подходят заранее заданные buckets histogram.
    """
    lspec = _labels_tuple({} if labels is None else {str(k): "" for k in labels.keys()})
    key = (name, lspec)
    if key not in _SUMMARIES:
        _SUMMARIES[key] = Summary(name, name, list(lspec))
    _SUMMARIES[key].labels(**_sanitize_labels(labels)).observe(float(value))
