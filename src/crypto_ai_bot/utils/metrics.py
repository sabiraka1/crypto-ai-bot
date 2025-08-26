from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Tuple, Optional

# Простой in-proc реестр метрик без внешних зависимостей.
# Поддерживаем:
#   - inc(name, labels)            -> Counter
#   - gauge_set(name, value, ...)  -> Gauge
#   - timer(name, labels)          -> Summary ( *_ms_sum / *_ms_count )
#   - render_prometheus()          -> текст в формате Prometheus
#   - render_metrics_json()        -> JSON-дамп всех метрик

# Внутренние структуры: ключ — (metric_name, frozenset(sorted(labels.items()))).
_COUNTERS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_GAUGES:  Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_SUM_MS:  Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_CNT:     Dict[Tuple[str, Tuple[Tuple[str, str], ...]], int]    = {}

def _lbls(labels: Optional[dict]) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return tuple()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

def _key(name: str, labels: Optional[dict]) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
    return (str(name), _lbls(labels))

def inc(name: str, labels: Optional[dict] = None, value: float = 1.0) -> None:
    k = _key(name, labels)
    _COUNTERS[k] = _COUNTERS.get(k, 0.0) + float(value)

def gauge_set(name: str, value: float, labels: Optional[dict] = None) -> None:
    _GAUGES[_key(name, labels)] = float(value)

@contextmanager
def timer(name: str, labels: Optional[dict] = None):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        k = _key(name, labels)
        _SUM_MS[k] = _SUM_MS.get(k, 0.0) + dt_ms
        _CNT[k] = _CNT.get(k, 0) + 1

def _fmt_labels(labels: Tuple[Tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in labels)
    return "{" + inner + "}"

def _sanitize(name: str) -> str:
    # Prometheus: только [a-zA-Z0-9:_]
    out = []
    for ch in name:
        out.append(ch if (ch.isalnum() or ch in [":", "_"]) else "_")
    return "".join(out)

def render_prometheus() -> str:
    # Counters
    lines = []
    for (name, labels), val in _COUNTERS.items():
        n = _sanitize(name)
        lines.append(f"{n}{_fmt_labels(labels)} {val}")
    # Gauges
    for (name, labels), val in _GAUGES.items():
        n = _sanitize(name)
        lines.append(f"{n}{_fmt_labels(labels)} {val}")
    # Timers -> *_ms_sum / *_ms_count
    for (name, labels), s in _SUM_MS.items():
        n = _sanitize(name)  # ожидаем имя вида "orchestrator_cycle_ms"
        c = _CNT.get((name, labels), 0)
        lines.append(f"{n}_sum{_fmt_labels(labels)} {s}")
        lines.append(f"{n}_count{_fmt_labels(labels)} {c}")
    return "\n".join(lines) + "\n"

def render_metrics_json() -> dict:
    to_key = lambda pair: {k: v for k, v in pair}
    return {
        "counters": [
            {"name": n, "labels": to_key(l), "value": v}
            for (n, l), v in _COUNTERS.items()
        ],
        "gauges": [
            {"name": n, "labels": to_key(l), "value": v}
            for (n, l), v in _GAUGES.items()
        ],
        "timers": [
            {"name": n, "labels": to_key(l), "sum_ms": _SUM_MS[(n, l)], "count": _CNT.get((n, l), 0)}
            for (n, l) in _SUM_MS.keys()
        ],
    }
