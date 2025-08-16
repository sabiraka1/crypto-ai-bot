from __future__ import annotations

import threading
from typing import Dict, Tuple


_lock = threading.Lock()
_counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_histograms: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_gauges: Dict[str, float] = {}  # name -> value


def _labels_tuple(labels: dict | None) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return tuple()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def inc(name: str, labels: dict | None = None, value: float = 1.0) -> None:
    key = (name, _labels_tuple(labels))
    with _lock:
        _counters[key] = _counters.get(key, 0.0) + float(value)


def observe(name: str, value: float, labels: dict | None = None) -> None:
    key = (name, _labels_tuple(labels))
    with _lock:
        _histograms[key] = _histograms.get(key, 0.0) + float(value)


def set_gauge(name: str, value: float) -> None:
    with _lock:
        _gauges[name] = float(value)


def export() -> str:
    """
    Возвращает Prometheus-совместимый текст.
    """
    with _lock:
        lines = []

        # Gauges
        for gname, val in sorted(_gauges.items()):
            lines.append(f'{gname} {val}')

        # Counters
        for (name, labels), v in sorted(_counters.items()):
            if labels:
                lab = ",".join(f'{k}="{v}"' for k, v in labels)
                lines.append(f'{name}{{{lab}}} {v}')
            else:
                lines.append(f'{name} {v}')

        # Simple sum histograms (без бакетов — упрощённо)
        for (name, labels), v in sorted(_histograms.items()):
            if labels:
                lab = ",".join(f'{k}="{v}"' for k, v in labels)
                lines.append(f'{name}_sum{{{lab}}} {v}')
            else:
                lines.append(f'{name}_sum {v}')

        return "\n".join(lines) + "\n"
