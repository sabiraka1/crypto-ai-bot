from __future__ import annotations

import threading
import time
from typing import Dict, Tuple

_lock = threading.Lock()
_counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_hist: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], list] = {}

def _labels_dict(labels) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return tuple()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

def inc(name: str, labels: Dict[str, str] | None = None, value: float = 1.0) -> None:
    key = (name, _labels_dict(labels))
    with _lock:
        _counters[key] = _counters.get(key, 0.0) + float(value)

def observe(name: str, value: float, labels: Dict[str, str] | None = None) -> None:
    key = (name, _labels_dict(labels))
    with _lock:
        _hist.setdefault(key, []).append(float(value))

def export_text() -> str:
    lines = []
    with _lock:
        for (name, labels), val in _counters.items():
            label_txt = ""
            if labels:
                label_txt = "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}"
            lines.append(f"{name}{label_txt} {val}")
        for (name, labels), arr in _hist.items():
            if not arr:
                continue
            label_txt = ""
            if labels:
                label_txt = "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}"
            # простые сводки: count/sum/last
            count = len(arr)
            s = sum(arr)
            last = arr[-1]
            lines.append(f"{name}_count{label_txt} {count}")
            lines.append(f"{name}_sum{label_txt} {s}")
            lines.append(f"{name}_last{label_txt} {last}")
    return "\n".join(lines) + "\n"
