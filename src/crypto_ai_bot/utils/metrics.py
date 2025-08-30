from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Dict, Tuple, Iterable

# Простая потокобезопасная реализация счётчиков и наблюдений
_lock = threading.RLock()

# counters[(name, frozenset(labels.items()))] = int
_counters: Dict[Tuple[str, frozenset], int] = defaultdict(int)

# gauges[(name, frozenset(labels.items()))] = float
_gauges: Dict[Tuple[str, frozenset], float] = defaultdict(float)

# histograms: сохраняем последние значения за N минут в простом «ведре»
_hist_values: Dict[Tuple[str, frozenset], list] = defaultdict(list)
_HIST_RETENTION_SEC = 15 * 60  # 15 минут

def _key(name: str, labels: Dict[str, str] | None) -> Tuple[str, frozenset]:
    return name, frozenset((labels or {}).items())

def inc(name: str, **labels) -> None:
    with _lock:
        _counters[_key(name, labels)] += 1

def set_gauge(name: str, value: float, **labels) -> None:
    with _lock:
        _gauges[_key(name, labels)] = float(value)

def observe(name: str, value: float, **labels) -> None:
    now = time.time()
    with _lock:
        k = _key(name, labels)
        arr = _hist_values[k]
        arr.append((now, float(value)))
        # очистка старья
        lim = now - _HIST_RETENTION_SEC
        while arr and arr[0][0] < lim:
            arr.pop(0)

def error_rate(labels: Dict[str, str] | None, window_sec: int) -> float:
    """
    Простейший расчёт: errors_total / requests_total за весь retention (для SLA — ок).
    Если хочешь полноценное окно — можно дополнить инкременты запросов/ошибок с timestamp.
    """
    with _lock:
        req = 0
        err = 0
        for (name, ll), v in _counters.items():
            if labels is not None and frozenset(labels.items()) != ll:
                continue
            if name.endswith("errors_total"):
                err += v
            if name.endswith("requests_total"):
                req += v
        if req <= 0:
            return 0.0
        return float(err) / float(req)

def avg_latency_ms(labels: Dict[str, str] | None, window_sec: int) -> float:
    with _lock:
        total = 0.0
        count = 0
        for (name, ll), arr in _hist_values.items():
            if name != "latency_ms":
                continue
            if labels is not None and frozenset(labels.items()) != ll:
                continue
            now = time.time()
            lim = now - min(window_sec, _HIST_RETENTION_SEC)
            vals = [v for ts, v in arr if ts >= lim]
            total += sum(vals)
            count += len(vals)
        return 0.0 if count == 0 else total / count

def render_prometheus() -> str:
    """
    Рендер метрик в формат Prometheus text exposition.
    """
    lines = []
    with _lock:
        if _counters:
            lines.append("# TYPE generic_counter counter")
            for (name, labels), v in _counters.items():
                lab = ",".join(f'{k}="{val}"' for k, val in dict(labels).items())
                lines.append(f'{name}{{{lab}}} {int(v)}')
        if _gauges:
            lines.append("# TYPE generic_gauge gauge")
            for (name, labels), v in _gauges.items():
                lab = ",".join(f'{k}="{val}"' for k, val in dict(labels).items())
                lines.append(f'{name}{{{lab}}} {float(v)}')
        # Гистограммы как summary (avg) для простоты
        if _hist_values:
            lines.append("# TYPE latency_summary gauge")
            for (name, labels), arr in _hist_values.items():
                if name != "latency_ms":
                    continue
                vals = [v for _, v in arr]
                avg = 0.0 if not vals else sum(vals) / len(vals)
                lab = ",".join(f'{k}="{val}"' for k, val in dict(labels).items())
                lines.append(f'{name}_avg{{{lab}}} {avg}')
    return "\n".join(lines) + "\n"

def render_metrics_json() -> dict:
    with _lock:
        return {
            "counters": {f"{name}|{dict(labels)}": v for (name, labels), v in _counters.items()},
            "gauges": {f"{name}|{dict(labels)}": v for (name, labels), v in _gauges.items()},
        }
