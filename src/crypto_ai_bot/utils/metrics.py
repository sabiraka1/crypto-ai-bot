# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Optional, Tuple

try:
    from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST  # type: ignore
    _PROM = True
    _REG = CollectorRegistry(auto_describe=True)
except Exception:  # pragma: no cover
    Counter = Gauge = Histogram = None  # type: ignore
    _PROM = False
    _REG = None

# Кэши регистраций, чтобы не плодить одинаковые метрики
_COUNTERS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Any] = {}
_GAUGES: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Any] = {}
_HISTS: Dict[Tuple[str, Tuple[Tuple[str, str], ...], Tuple[float, ...]], Any] = {}

_DEFAULT_BUCKETS_MS = (10, 25, 50, 100, 200, 500, 1000, 2000, 5000, 10000)

def _labels_tuple(labels: Optional[Dict[str, str]]) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return tuple()
    # prometheus требует str-строки, сортируем для стабильности ключа
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

def inc(name: str, labels: Optional[Dict[str, str]] = None, amount: float = 1.0) -> None:
    if not _PROM:
        return
    key = (name, _labels_tuple(labels))
    c = _COUNTERS.get(key)
    if c is None:
        # имена лейблов — из ключей labels
        lbls = [kv[0] for kv in key[1]]
        c = Counter(name, f"{name} counter", labelnames=lbls, registry=_REG)
        _COUNTERS[key] = c
    if key[1]:
        c.labels(**{k: v for k, v in key[1]}).inc(amount)
    else:
        c.inc(amount)

def set_gauge(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    if not _PROM:
        return
    key = (name, _labels_tuple(labels))
    g = _GAUGES.get(key)
    if g is None:
        lbls = [kv[0] for kv in key[1]]
        g = Gauge(name, f"{name} gauge", labelnames=lbls, registry=_REG)
        _GAUGES[key] = g
    if key[1]:
        g.labels(**{k: v for k, v in key[1]}).set(value)
    else:
        g.set(value)

def observe_histogram(
    name: str,
    value_ms: float,
    labels: Optional[Dict[str, str]] = None,
    buckets_ms: Tuple[float, ...] = _DEFAULT_BUCKETS_MS,
) -> None:
    if not _PROM:
        return
    key = (name, _labels_tuple(labels), buckets_ms)
    h = _HISTS.get(key)
    if h is None:
        lbls = [kv[0] for kv in key[1]]
        h = Histogram(name, f"{name} histogram (ms)", labelnames=lbls, registry=_REG, buckets=buckets_ms)  # type: ignore[arg-type]
        _HISTS[key] = h
    if key[1]:
        h.labels(**{k: v for k, v in key[1]}).observe(float(value_ms))
    else:
        h.observe(float(value_ms))

@contextmanager
def timer(name: str, labels: Optional[Dict[str, str]] = None) -> Any:
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        observe_histogram(name, dt_ms, labels=labels)

# --------- /metrics экспорт (без зависимости на FastAPI) ---------

def prometheus_app(environ, start_response):  # type: ignore
    """
    WSGI-совместимый экспорт метрик. Можно повесить на /metrics в FastAPI.
    """
    if not _PROM:
        body = b"# no prometheus_client installed\n"
        start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))])
        return [body]
    output = generate_latest(_REG)  # type: ignore
    start_response("200 OK", [("Content-Type", CONTENT_TYPE_LATEST), ("Content-Length", str(len(output)))])  # type: ignore
    return [output]
