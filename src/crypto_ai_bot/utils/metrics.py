from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Tuple, Optional

# ============ IN-MEMORY РЕЕСТР ============
_LabelKey = Tuple[Tuple[str, str], ...]  # отсортированная кортеж-форма меток (k,v)

_counters: Dict[str, Dict[_LabelKey, float]] = {}
_histograms: Dict[str, Dict[_LabelKey, Dict[str, float]]] = {}
# hist: {"count": c, "sum": s, "min": m, "max": M}

def _norm_labels(labels: Optional[Dict[str, str]]) -> _LabelKey:
    if not labels:
        return tuple()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

# ============ ПУБЛИЧНОЕ API ============

def inc(name: str, labels: Optional[Dict[str, str]] = None, value: float = 1.0) -> None:
    series = _counters.setdefault(name, {})
    key = _norm_labels(labels)
    series[key] = series.get(key, 0.0) + float(value)

def observe(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    series = _histograms.setdefault(name, {})
    key = _norm_labels(labels)
    s = series.get(key)
    if s is None:
        series[key] = {"count": 1.0, "sum": float(value), "min": float(value), "max": float(value)}
    else:
        s["count"] += 1.0
        s["sum"] += float(value)
        s["min"] = min(s["min"], float(value))
        s["max"] = max(s["max"], float(value))

@contextmanager
def timer(name: str, labels: Optional[Dict[str, str]] = None, *, unit: str = "seconds"):
    """
    Таймер: наблюдаем длительность как summary (count/sum/min/max).
    unit: "seconds" | "ms" (по умолчанию — секунды).
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        dur = time.perf_counter() - start
        if unit == "ms":
            dur *= 1000.0
        observe(name, dur, labels)

def snapshot() -> Dict[str, object]:
    """Снимок текущих значений (для JSON-фолбэка и тестов)."""
    def _labels_to_dict(key: _LabelKey) -> Dict[str, str]:
        return {k: v for k, v in key}

    return {
        "counters": {
            name: [{"labels": _labels_to_dict(k), "value": v} for k, v in series.items()]
            for name, series in _counters.items()
        },
        "histograms": {
            name: [{"labels": _labels_to_dict(k), **stats} for k, stats in series.items()]
            for name, series in _histograms.items()
        },
    }

# ============ ПРОМЕТЕЕВСКИЙ ТЕКСТ (ФОЛБЭК) ============

def prometheus_text_or_none() -> Optional[str]:
    """
    Простой текст в стиле Prometheus. Возвращает None, если метрик нет вовсе.
    """
    if not _counters and not _histograms:
        return None

    lines: list[str] = []
    # counters
    for name, series in _counters.items():
        lines.append(f"# TYPE {name} counter")
        for key, val in series.items():
            if key:
                lbl = ",".join(f'{k}="{v}"' for k, v in key)
                lines.append(f"{name}{{{lbl}}} {val}")
            else:
                lines.append(f"{name} {val}")

    # histograms как summary: *_count и *_sum (без бакетов)
    for name, series in _histograms.items():
        lines.append(f"# TYPE {name}_count counter")
        lines.append(f"# TYPE {name}_sum gauge")
        for key, stats in series.items():
            if key:
                lbl = ",".join(f'{k}="{v}"' for k, v in key)
                lines.append(f"{name}_count{{{lbl}}} {stats.get('count', 0)}")
                lines.append(f"{name}_sum{{{lbl}}} {stats.get('sum', 0.0)}")
            else:
                lines.append(f"{name}_count {stats.get('count', 0)}")
                lines.append(f"{name}_sum {stats.get('sum', 0.0)}")
    return "\n".join(lines) + "\n"
