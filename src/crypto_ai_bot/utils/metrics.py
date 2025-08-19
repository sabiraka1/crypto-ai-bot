# utils/metrics.py
from __future__ import annotations

import math
import threading
from collections import defaultdict
from typing import Dict, Tuple, Optional


_lock = threading.Lock()
_counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
_gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
_histograms: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Dict[str, float]] = defaultdict(lambda: defaultdict(float))

_DEFAULT_BUCKETS = [0.5, 1, 2, 5, 10, 25, 50, 100, 250, 500, 1000]  # мс/бпс — на вкус


def _labels(lbl: Optional[Dict[str, str]]) -> Tuple[Tuple[str, str], ...]:
    if not lbl:
        return tuple()
    return tuple(sorted((str(k), str(v)) for k, v in lbl.items()))


def inc(name: str, labels: Optional[Dict[str, str]] = None, value: float = 1.0) -> None:
    with _lock:
        _counters[(name, _labels(labels))] += float(value)


def gauge(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    with _lock:
        _gauges[(name, _labels(labels))] = float(value)


def observe_histogram(name: str, value: float, labels: Optional[Dict[str, str]] = None, buckets=_DEFAULT_BUCKETS) -> None:
    key = (name, _labels(labels))
    v = float(value)
    with _lock:
        for b in buckets:
            if v <= b:
                _histograms[key][f"le_{b}"] += 1.0
        _histograms[key]["sum"] += v
        _histograms[key]["count"] += 1.0


def export() -> str:
    lines = []
    with _lock:
        for (name, lbl), val in _counters.items():
            suffix = "".join([f'{{{",".join(f"{k}=\"{v}\"" for k,v in lbl)}}}' if lbl else ""])
            lines.append(f"{name}{suffix} {val}")
        for (name, lbl), val in _gauges.items():
            suffix = "".join([f'{{{",".join(f"{k}=\"{v}\"" for k,v in lbl)}}}' if lbl else ""])
            lines.append(f"{name}{suffix} {val}")
        for (name, lbl), buckets in _histograms.items():
            base = f"{name}_bucket"
            suffix = "".join([f'{{{",".join(f"{k}=\"{v}\"" for k,v in lbl)}}}' if lbl else ""])
            for k, v in buckets.items():
                if k.startswith("le_"):
                    lines.append(f"{base}{suffix},le=\"{k[3:]}\") {v}")
            # итоги
            s = buckets.get("sum", 0.0)
            c = buckets.get("count", 0.0)
            base_nolbl = f"{name}_sum"
            lines.append(f"{base_nolbl}{suffix} {s}")
            lines.append(f"{name}_count{suffix} {c}")
    return "\n".join(lines) + "\n"
