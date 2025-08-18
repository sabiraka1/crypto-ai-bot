# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations

import threading
import time
from typing import Dict, Tuple, Optional, List

_LabelKey = Tuple[str, Tuple[Tuple[str, str], ...]]  # (name, sorted(label_items))

def _labels_key(name: str, labels: Optional[Dict[str, str]]) -> _LabelKey:
    if not labels:
        return (name, tuple())
    return (name, tuple(sorted((str(k), str(v)) for k, v in labels.items())))

def _labels_text(labels: Optional[Dict[str, str]]) -> str:
    if not labels:
        return ""
    parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(parts) + "}"

_lock = threading.RLock()

_counters: Dict[_LabelKey, float] = {}
_gauges:   Dict[_LabelKey, float] = {}

class _Hist:
    __slots__ = ("buckets", "counts", "sum", "count")
    def __init__(self, buckets: List[float]) -> None:
        bs = sorted(float(b) for b in buckets if b is not None)
        if not bs:
            bs = _DEFAULT_BUCKETS[:]
        self.buckets = bs
        self.counts: List[float] = [0.0 for _ in bs]
        self.sum: float = 0.0
        self.count: float = 0.0

_histograms: Dict[_LabelKey, _Hist] = {}

_DEFAULT_BUCKETS: List[float] = [
    0.005, 0.01, 0.025, 0.05, 0.1,
    0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
]

_metric_buckets: Dict[str, List[float]] = {}

def set_default_buckets(metric_name: str, buckets: List[float]) -> None:
    with _lock:
        _metric_buckets[metric_name] = sorted(float(b) for b in buckets if b is not None)

def inc(name: str, labels: Optional[Dict[str, str]] = None, value: float = 1.0) -> None:
    key = _labels_key(name, labels)
    with _lock:
        _counters[key] = _counters.get(key, 0.0) + float(value)

def gauge(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    key = _labels_key(name, labels)
    with _lock:
        _gauges[key] = float(value)

def observe_histogram(
    name: str,
    value_seconds: float,
    labels: Optional[Dict[str, str]] = None,
    buckets: Optional[List[float]] = None,
) -> None:
    key = _labels_key(name, labels)
    with _lock:
        if buckets is None:
            buckets = _metric_buckets.get(name) or _DEFAULT_BUCKETS
        hist = _histograms.get(key)
        if hist is None:
            hist = _Hist(buckets)
            _histograms[key] = hist
        v = float(value_seconds)
        hist.sum += v
        hist.count += 1.0
        for i, le in enumerate(hist.buckets):
            if v <= le:
                hist.counts[i] += 1.0

def export() -> str:
    out: List[str] = []
    with _lock:
        if _counters:
            names_emitted = set(n for (n, _l) in _counters.keys())
            for n in sorted(names_emitted):
                out.append(f"# TYPE {n} counter")
            for (n, labels), v in sorted(_counters.items()):
                out.append(f"{n}{_labels_text(dict(labels))} {int(v) if float(v).is_integer() else v}")

        if _gauges:
            names_emitted = set(n for (n, _l) in _gauges.keys())
            for n in sorted(names_emitted):
                out.append(f"# TYPE {n} gauge")
            for (n, labels), v in sorted(_gauges.items()):
                out.append(f"{n}{_labels_text(dict(labels))} {v}")

        if _histograms:
            names_emitted = set(n for (n, _l) in _histograms.keys())
            for n in sorted(names_emitted):
                out.append(f"# TYPE {n} histogram")
            for (n, labels), h in sorted(_histograms.items()):
                for i, le in enumerate(h.buckets):
                    acc = h.counts[i]
                    out.append(f'{n}_bucket{_labels_text({**(dict(labels) or {}), "le": str(le)})} {int(acc) if float(acc).is_integer() else acc}')
                out.append(f'{n}_bucket{_labels_text({**(dict(labels) or {}), "le": "+Inf"})} {int(h.count) if float(h.count).is_integer() else h.count}')
                out.append(f"{n}_sum{_labels_text(dict(labels))} {h.sum}")
                out.append(f"{n}_count{_labels_text(dict(labels))} {int(h.count) if float(h.count).is_integer() else h.count}")
    return "\n".join(out) + ("\n" if out else "")

class _Timer:
    __slots__ = ("_t0", "elapsed")
    def __init__(self) -> None:
        self._t0 = 0.0
        self.elapsed = 0.0
    def __enter__(self) -> "_Timer":
        self._t0 = time.perf_counter()
        return self
    def __exit__(self, exc_type, exc, tb) -> None:
        self.elapsed = time.perf_counter() - self._t0

def timer() -> _Timer:
    return _Timer()

def check_performance_budget(kind: str, elapsed_seconds: float, budget_ms: Optional[int]) -> None:
    if not budget_ms:
        return
    try:
        if (elapsed_seconds * 1000.0) > float(budget_ms):
            inc("performance_budget_single_exceeded_total", {"kind": str(kind)})
    except Exception:
        pass

# ---- ШИМ-СОВМЕСТИМОСТЬ: старые вызовы в миллисекундах ----
def observe_ms(name: str, value_ms: float, labels: Optional[Dict[str, str]] = None, buckets_ms: Optional[List[float]] = None) -> None:
    """
    Back-compat: наблюдение в миллисекундах. Внутри конвертирует в секунды.
    """
    secs = float(value_ms) / 1000.0
    buckets = [float(b) / 1000.0 for b in (buckets_ms or [])] if buckets_ms else None
    observe_histogram(name, secs, labels=labels, buckets=buckets)

# alias: многие проекты называли именно observe_hist(...)
observe_hist = observe_ms  # type: ignore
