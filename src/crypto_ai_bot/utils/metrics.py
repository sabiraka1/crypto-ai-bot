from __future__ import annotations

import threading
from typing import Dict, Tuple, FrozenSet, Any

# Простой встроенный сборщик метрик (без внешних библиотек).
# Использование:
#   from ...utils.metrics import inc, render_prometheus
#   inc("orc_eval_ticks_total")
#   inc("orders_placed_total", side="buy")

_LOCK = threading.RLock()
_COUNTERS: Dict[Tuple[str, FrozenSet[Tuple[str, str]]], int] = {}

_HELP: Dict[str, str] = {
    "orc_eval_ticks_total": "Number of eval loop ticks",
    "orders_placed_total": "Orders placed",
    "orders_blocked_total": "Orders blocked by risk",
    "exits_triggered_total": "Protective exits executed",
    "watchdog_heartbeat_total": "Watchdog heartbeats",
    "errors_total": "Errors observed",
}

_TYPE: Dict[str, str] = {
    "orc_eval_ticks_total": "counter",
    "orders_placed_total": "counter",
    "orders_blocked_total": "counter",
    "exits_triggered_total": "counter",
    "watchdog_heartbeat_total": "counter",
    "errors_total": "counter",
}


def inc(name: str, **labels: Any) -> None:
    """Увеличить счётчик (по метке уникально)."""
    lab: FrozenSet[Tuple[str, str]] = frozenset((k, str(v)) for k, v in sorted(labels.items()))
    key = (name, lab)
    with _LOCK:
        _COUNTERS[key] = _COUNTERS.get(key, 0) + 1


def render_prometheus() -> str:
    # Текстовая экспозиция Prometheus
    lines = []
    with _LOCK:
        for metric, typ in _TYPE.items():
            help_text = _HELP.get(metric, metric)
            lines.append(f"# HELP {metric} {help_text}")
            lines.append(f"# TYPE {metric} {typ}")
            # вывести все комбинации меток для данного метрика
            for (name, lab), value in _COUNTERS.items():
                if name != metric:
                    continue
                if lab:
                    labels = ",".join(f'{k}="{v}"' for k, v in lab)
                    lines.append(f"{metric}{{{labels}}} {value}")
                else:
                    lines.append(f"{metric} {value}")
    return "\n".join(lines) + "\n"


def render_metrics_json() -> str:
    # на случай, когда хотим отдать JSON вместо текстового формата
    with _LOCK:
        arr = []
        for (name, lab), value in _COUNTERS.items():
            arr.append({"name": name, "labels": dict(lab), "value": value})
    return str({"counters": arr})
