from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Dict, Tuple, Optional, Iterable

_LabelKey = Tuple[Tuple[str, str], ...]

def _norm_labels(labels: Optional[dict]) -> _LabelKey:
    if not labels:
        return tuple()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        # counters: name -> {label_tuple: float}
        self._counters: Dict[str, Dict[_LabelKey, float]] = defaultdict(lambda: defaultdict(float))
        # gauges: name -> {label_tuple: float}
        self._gauges: Dict[str, Dict[_LabelKey, float]] = defaultdict(lambda: defaultdict(float))
        # histograms: name -> (buckets_sorted, {label_tuple: {le_value: count}}, {label_tuple: sum}, {label_tuple: count})
        self._h_buckets: Dict[str, Tuple[Tuple[float, ...], Dict[_LabelKey, Dict[float, int]], Dict[_LabelKey, float], Dict[_LabelKey, int]]] = {}

    # ---- public API ----
    def inc(self, name: str, labels: Optional[dict] = None, value: float = 1.0) -> None:
        lab = _norm_labels(labels)
        with self._lock:
            self._counters[name][lab] += float(value)

    def observe(self, name: str, value: float, labels: Optional[dict] = None, buckets: Optional[Iterable[float]] = None) -> None:
        """
        Если buckets=None — ведём себя как gauge (последнее значение).
        Если buckets задан — реализуем Prometheus-подобный histogram:
          name_bucket{le="..."} N
          name_count N
          name_sum S
        """
        lab = _norm_labels(labels)
        v = float(value)
        with self._lock:
            if not buckets:
                self._gauges[name][lab] = v
                return
            # histogram
            b_sorted = tuple(sorted(float(b) for b in buckets))
            if name not in self._h_buckets:
                self._h_buckets[name] = (b_sorted, defaultdict(lambda: defaultdict(int)), defaultdict(float), defaultdict(int))
            else:
                existing_b, _, _, _ = self._h_buckets[name]
                if existing_b != b_sorted:
                    # Если кто-то поменял набор бакетов — игнорируем новые, чтобы не ломать экспозицию.
                    b_sorted = existing_b
            b_sorted, bucket_map, sums, counts = self._h_buckets[name]
            # инкремент соответствующих бакетов (включая +Inf)
            le_counts = bucket_map[lab]
            placed = False
            for le in b_sorted:
                if v <= le:
                    le_counts[le] += 1
                    placed = True
            if not placed:
                # значение больше всех бакетов → попадёт только в +Inf на экспорте
                pass
            sums[lab] += v
            counts[lab] += 1

    def export(self) -> str:
        """
        Экспорт в Prometheus text format 0.0.4.
        """
        lines = []
        with self._lock:
            # counters
            for name, bylab in self._counters.items():
                for lab, val in bylab.items():
                    if lab:
                        lab_s = ",".join(f'{k}="{v}"' for k, v in lab)
                        lines.append(f'{name}{{{lab_s}}} {val}')
                    else:
                        lines.append(f'{name} {val}')
            # gauges
            for name, bylab in self._gauges.items():
                for lab, val in bylab.items():
                    if lab:
                        lab_s = ",".join(f'{k}="{v}"' for k, v in lab)
                        lines.append(f'{name}{{{lab_s}}} {val}')
                    else:
                        lines.append(f'{name} {val}')
            # histograms
            for name, (b_sorted, bucket_map, sums, counts) in self._h_buckets.items():
                for lab, le_counts in bucket_map.items():
                    # накопительные бакеты
                    cumulative = 0
                    for le in b_sorted:
                        cumulative += le_counts.get(le, 0)
                        lab_items = list(lab) + [("le", str(le))]
                        lab_s = ",".join(f'{k}="{v}"' for k, v in sorted(lab_items))
                        lines.append(f'{name}_bucket{{{lab_s}}} {cumulative}')
                    # +Inf
                    total = counts.get(lab, 0)
                    lab_items = list(lab) + [("le", "+Inf")]
                    lab_s = ",".join(f'{k}="{v}"' for k, v in sorted(lab_items))
                    lines.append(f'{name}_bucket{{{lab_s}}} {total}')
                    # _sum/_count
                    sum_v = sums.get(lab, 0.0)
                    if lab:
                        lab_s2 = ",".join(f'{k}="{v}"' for k, v in lab)
                        lines.append(f'{name}_sum{{{lab_s2}}} {sum_v}')
                        lines.append(f'{name}_count{{{lab_s2}}} {total}')
                    else:
                        lines.append(f'{name}_sum {sum_v}')
                        lines.append(f'{name}_count {total}')
        return "\n".join(lines) + ("\n" if lines else "")

# Singleton
_metrics = _Metrics()

def inc(name: str, labels: Optional[dict] = None, value: float = 1.0) -> None:
    _metrics.inc(name, labels, value)

def observe(name: str, value: float, labels: Optional[dict] = None, buckets: Optional[Iterable[float]] = None) -> None:
    _metrics.observe(name, value, labels, buckets)

def export() -> str:
    return _metrics.export()
