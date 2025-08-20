# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations
from typing import Dict, Optional

# Safe Prometheus wrappers (work even if prometheus_client isn't installed)
try:
    from prometheus_client import Counter, Histogram, Summary
except Exception:  # pragma: no cover
    Counter = Histogram = Summary = None  # type: ignore

_METRICS: Dict[str, object] = {}

def _labels(lbl: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    # ensure string-only labels
    if not lbl:
        return {}
    return {str(k): str(v) for k, v in lbl.items()}

def inc(name: str, labels: Optional[Dict[str, str]] = None, help: str = "counter") -> None:
    if Counter is None:
        return
    key = f"C:{name}"
    if key not in _METRICS:
        _METRICS[key] = Counter(name, help, list(_labels(labels).keys()) or None)  # type: ignore
    metric: Counter = _METRICS[key]  # type: ignore
    (metric.labels(**_labels(labels)) if labels else metric).inc()  # type: ignore

def observe_histogram(name: str, value: float, labels: Optional[Dict[str, str]] = None,
                      help: str = "histogram", buckets=None) -> None:
    if Histogram is None:
        return
    key = f"H:{name}"
    if key not in _METRICS:
        _METRICS[key] = Histogram(name, help, list(_labels(labels).keys()) or None, buckets=buckets)  # type: ignore
    metric: Histogram = _METRICS[key]  # type: ignore
    (metric.labels(**_labels(labels)) if labels else metric).observe(value)  # type: ignore

def observe_summary(name: str, value: float, labels: Optional[Dict[str, str]] = None,
                    help: str = "summary") -> None:
    if Summary is None:
        return
    key = f"S:{name}"
    if key not in _METRICS:
        _METRICS[key] = Summary(name, help, list(_labels(labels).keys()) or None)  # type: ignore
    metric: Summary = _METRICS[key]  # type: ignore
    (metric.labels(**_labels(labels)) if labels else metric).observe(value)  # type: ignore

# Convenience shorthands used by the app:

def record_slippage_bps(symbol: str, side: str, bps: float) -> None:
    observe_histogram(
        "trade_slippage_bps", bps,
        {"symbol": symbol, "side": side},
        help="Measured slippage in basis points (absolute)",
        buckets=(1, 2, 5, 10, 20, 50, 100, 200, 400, 800),
    )

def record_order_latency_ms(symbol: str, side: str, ms: int) -> None:
    observe_summary("order_latency_ms", float(ms), {"symbol": symbol, "side": side},
                    help="Latency from decision to order accepted")

def inc_protective_exits_triggered(symbol: str) -> None:
    inc("protective_exits_triggered_total", {"symbol": symbol})

def inc_reconcile_errors(symbol: str) -> None:
    inc("reconcile_errors_total", {"symbol": symbol})
