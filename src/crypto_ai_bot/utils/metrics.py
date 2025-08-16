# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations

import threading
import time
from typing import Dict, Tuple, FrozenSet, Optional

_LabelKey = Tuple[str, FrozenSet[Tuple[str, str]]]

_lock = threading.Lock()
_counters: Dict[_LabelKey, float] = {}
_summaries: Dict[_LabelKey, Dict[str, float]] = {}
_gauges: Dict[_LabelKey, float] = {}

def _norm_labels(labels: Optional[dict]) -> FrozenSet[Tuple[str, str]]:
    if not labels:
        return frozenset()
    # Строго сортируем ключи — стабильно для экспорта
    return frozenset((str(k), str(v)) for k, v in sorted(labels.items()))

def _key(name: str, labels: Optional[dict]) -> _LabelKey:
    return (name, _norm_labels(labels))

def inc(name: str, labels: Optional[dict] = None, value: float = 1.0) -> None:
    k = _key(name, labels)
    with _lock:
        _counters[k] = _counters.get(k, 0.0) + float(value)

def observe(name: str, value: float, labels: Optional[dict] = None) -> None:
    """Простая summary-метрика: *_sum и *_count."""
    k = _key(name, labels)
    with _lock:
        s = _summaries.get(k)
        if s is None:
            s = {"sum": 0.0, "count": 0.0}
            _summaries[k] = s
        s["sum"] += float(value)
        s["count"] += 1.0

def set_gauge(name: str, value: float, labels: Optional[dict] = None) -> None:
    """Gauge — текущее значение (перезаписывается)."""
    k = _key(name, labels)
    with _lock:
        _gauges[k] = float(value)

def _fmt_labels(labels: FrozenSet[Tuple[str, str]]) -> str:
    if not labels:
        return ""
    parts = []
    for k, v in labels:
        v = v.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'{k}="{v}"')
    return "{" + ",".join(parts) + "}"

def export() -> str:
    """Возвращает весь реестр метрик в формате Prometheus."""
    lines = []
    now = int(time.time())

    with _lock:
        # COUNTERS
        for (name, labels), val in sorted(_counters.items(), key=lambda x: (x[0][0], tuple(x[0][1]))):
            lines.append(f"{name}{_fmt_labels(labels)} {val}")

        # SUMMARIES (как счётчики *_sum и *_count)
        for (name, labels), s in sorted(_summaries.items(), key=lambda x: (x[0][0], tuple(x[0][1]))):
            lines.append(f"{name}_sum{_fmt_labels(labels)} {s['sum']}")
            lines.append(f"{name}_count{_fmt_labels(labels)} {s['count']}")

        # GAUGES
        for (name, labels), val in sorted(_gauges.items(), key=lambda x: (x[0][0], tuple(x[0][1]))):
            lines.append(f"{name}{_fmt_labels(labels)} {val}")

    # Немного служебной информации (по желанию)
    lines.append(f'export_ts_seconds {now}')
    return "\n".join(lines) + "\n"

# Удобно для тестов
def _reset_all() -> None:
    with _lock:
        _counters.clear()
        _summaries.clear()
        _gauges.clear()
