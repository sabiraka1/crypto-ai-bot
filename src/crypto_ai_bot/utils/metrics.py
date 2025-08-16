# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations

import threading
import time
from typing import Dict, Tuple, Optional

# Внутреннее хранилище
_lock = threading.Lock()
_counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_summaries: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Tuple[float, int]] = {}  # (sum, count)


def _lab_tuple(labels: Optional[dict]) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def inc(name: str, labels: Optional[dict] = None, value: float = 1.0) -> None:
    key = (name, _lab_tuple(labels))
    with _lock:
        _counters[key] = _counters.get(key, 0.0) + float(value)


def observe(name: str, value: float, labels: Optional[dict] = None) -> None:
    key = (name, _lab_tuple(labels))
    with _lock:
        s, c = _summaries.get(key, (0.0, 0))
        _summaries[key] = (s + float(value), c + 1)


def export() -> str:
    """
    Простейший Prometheus text format (counters + summaries).
    """
    lines = []
    ts = int(time.time())
    with _lock:
        # counters
        for (metric, labels), val in _counters.items():
            lab = ""
            if labels:
                lab = "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}"
            lines.append(f"{metric}{lab} {val}")
        # summaries (как _sum/_count)
        for (metric, labels), (s, c) in _summaries.items():
            lab = ""
            if labels:
                lab = "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}"
            lines.append(f"{metric}_sum{lab} {s}")
            lines.append(f"{metric}_count{lab} {c}")
    return "\n".join(lines) + "\n"
