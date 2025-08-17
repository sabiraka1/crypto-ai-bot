# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations

import threading
from typing import Dict, Tuple, Optional, Iterable

_lock = threading.Lock()

# key = (name, labels_tuple) → value
_counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
# для совместимости со "суммами": name_sum; но добавим и bucket-метрики
_hist_sums: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_hist_counts: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_hist_buckets: Dict[Tuple[str, Tuple[Tuple[str, str], ...], str], float] = {}  # (name, labels), le -> count

def _labels_tuple(labels: dict | None) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return tuple()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

def inc(name: str, labels: dict | None = None, value: float = 1.0) -> None:
    key = (name, _labels_tuple(labels))
    with _lock:
        _counters[key] = _counters.get(key, 0.0) + float(value)

def gauge(name: str, value: float, labels: dict | None = None) -> None:
    key = (name, _labels_tuple(labels))
    with _lock:
        _gauges[key] = float(value)

# старое имя — оставляем как алиас
def set_gauge(name: str, value: float) -> None:
    gauge(name, value, None)

def observe(name: str, value: float, labels: dict | None = None) -> None:
    # совместимость со старым API: просто суммируем
    key = (name, _labels_tuple(labels))
    with _lock:
        _hist_sums[key] = _hist_sums.get(key, 0.0) + float(value)
        _hist_counts[key] = _hist_counts.get(key, 0.0) + 1.0

def observe_histogram(
    name: str,
    value: float,
    labels: dict | None = None,
    *,
    buckets: Optional[Iterable[float]] = None,
) -> None:
    """
    Полноценная Prometheus-подобная гистограмма:
      {name}_bucket{...,le="X"} count
      {name}_bucket{...,le="+Inf"} count
      {name}_sum{...} sum
      {name}_count{...} count
    """
    labs = _labels_tuple(labels)
    bs = list(buckets or (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0))  # секунды по умолчанию
    v = float(value)

    with _lock:
        placed = False
        for b in bs:
            if v <= b:
                _hist_buckets[(name, labs, str(b))] = _hist_buckets.get((name, labs, str(b)), 0.0) + 1.0
                placed = True
        # +Inf
        _hist_buckets[(name, labs, "+Inf")] = _hist_buckets.get((name, labs, "+Inf"), 0.0) + 1.0

        _hist_sums[(name, labs)] = _hist_sums.get((name, labs), 0.0) + v
        _hist_counts[(name, labs)] = _hist_counts.get((name, labs), 0.0) + 1.0

def export() -> str:
    """
    Возвращает Prometheus-текст (версия 0.0.4).
    """
    with _lock:
        lines = []

        # Gauges
        for (name, labels), val in sorted(_gauges.items()):
            if labels:
                lab = ",".join(f'{k}="{v}"' for k, v in labels)
                lines.append(f'{name}{{{lab}}} {val}')
            else:
                lines.append(f'{name} {val}')

        # Counters
        for (name, labels), val in sorted(_counters.items()):
            if labels:
                lab = ",".join(f'{k}="{v}"' for k, v in labels)
                lines.append(f'{name}{{{lab}}} {val}')
            else:
                lines.append(f'{name} {val}')

        # Histograms: buckets
        for (name, labels, le), cnt in sorted(_hist_buckets.items()):
            if labels:
                lab = ",".join(f'{k}="{v}"' for k, v in labels)
                lines.append(f'{name}_bucket{{{lab},le="{le}"}} {cnt}')
            else:
                lines.append(f'{name}_bucket{{le="{le}"}} {cnt}')

        # Histograms: sum & count
        for (name, labels), s in sorted(_hist_sums.items()):
            c = _hist_counts.get((name, labels), 0.0)
            if labels:
                lab = ",".join(f'{k}="{v}"' for k, v in labels)
                lines.append(f'{name}_sum{{{lab}}} {s}')
                lines.append(f'{name}_count{{{lab}}} {c}')
            else:
                lines.append(f'{name}_sum {s}')
                lines.append(f'{name}_count {c}')

        return "\n".join(lines) + "\n"
