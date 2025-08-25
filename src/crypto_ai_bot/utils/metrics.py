from __future__ import annotations

import time
from contextlib import contextmanager
from threading import RLock
from typing import Any, Dict, Tuple, FrozenSet, List

_lock = RLock()

_counters: Dict[str, Dict[FrozenSet[Tuple[str, str]], int]] = {}
_summaries: Dict[str, Dict[FrozenSet[Tuple[str, str]], Tuple[int, float]]] = {}


def _norm_labels(labels: Dict[str, Any] | None) -> FrozenSet[Tuple[str, str]]:
    if not labels:
        return frozenset()
    return frozenset((str(k), str(v)) for k, v in sorted(labels.items(), key=lambda x: x[0]))


def inc(name: str, labels: Dict[str, Any] | None = None, amount: int = 1, **kwargs: Any) -> None:
    if "value" in kwargs:
        try:
            amount = int(kwargs["value"])  # type: ignore[assignment]
        except Exception:
            amount = 1
    lab = _norm_labels(labels)
    with _lock:
        bucket = _counters.setdefault(name, {})
        bucket[lab] = bucket.get(lab, 0) + int(amount)


def observe(name: str, value: float, labels: Dict[str, Any] | None = None) -> None:
    lab = _norm_labels(labels)
    with _lock:
        bucket = _summaries.setdefault(name, {})
        cnt, s = bucket.get(lab, (0, 0.0))
        bucket[lab] = (cnt + 1, s + float(value))


@contextmanager
def timer(name: str, labels: Dict[str, Any] | None = None):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = (time.perf_counter() - t0)
        observe(name, dt, labels)


def snapshot() -> Dict[str, Any]:
    with _lock:
        out: Dict[str, Any] = {"counters": {}, "histograms": {}}
        for name, series in _counters.items():
            items: List[Dict[str, Any]] = []
            for lab, val in series.items():
                items.append({
                    "labels": {k: v for k, v in lab},
                    "value": float(val),
                })
            out["counters"][name] = items
        for name, series in _summaries.items():
            items = []
            for lab, (cnt, s) in series.items():
                items.append({
                    "labels": {k: v for k, v in lab},
                    "count": float(cnt),
                    "sum": float(s),
                })
            out["histograms"][name] = items
        return out


def render_prometheus() -> str:
    lines: list[str] = []

    with _lock:
        for name, series in _counters.items():
            lines.append(f"# TYPE {name} counter")
            for lab, val in series.items():
                if lab:
                    lab_s = ",".join(f'{k}="{v}"' for k, v in lab)
                    lines.append(f'{name}{{{lab_s}}} {val}')
                else:
                    lines.append(f"{name} {val}")
        for name, series in _summaries.items():
            lines.append(f"# TYPE {name} summary")
            for lab, (cnt, s) in series.items():
                if lab:
                    lab_s = ",".join(f'{k}="{v}"' for k, v in lab)
                    lines.append(f'{name}_count{{{lab_s}}} {cnt}')
                    lines.append(f'{name}_sum{{{lab_s}}} {s}')
                else:
                    lines.append(f"{name}_count {cnt}")
                    lines.append(f"{name}_sum {s}")
    return "\n".join(lines) + "\n"