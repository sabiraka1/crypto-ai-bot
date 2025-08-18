# src/crypto_ai_bot/core/events/factory.py
from __future__ import annotations

import time
from typing import Any, Dict, Mapping

# Значения backpressure — подсказки для async_bus:
#   policy: "drop_oldest" | "drop_new" | "block" | "coalesce"
#   max_queue: лимит длины очереди для данного типа
#   priority: 1..10 (1 — самый высокий)
DEFAULT_BACKPRESSURE_MAP: Dict[str, Dict[str, Any]] = {
    "OrderExecuted":   {"policy": "block",      "max_queue": 1000, "priority": 1},
    "DecisionEvaluated": {"policy": "coalesce", "max_queue": 5000, "priority": 3},
    "PositionChanged": {"policy": "drop_oldest","max_queue": 2000, "priority": 4},
    "AuditEvent":      {"policy": "drop_oldest","max_queue": 5000, "priority": 7},
    "MetricFlush":     {"policy": "coalesce",   "max_queue": 50,   "priority": 8},
    "LogEvent":        {"policy": "drop_new",   "max_queue": 10000,"priority": 9},
}

def build_event(type_: str, **payload: Any) -> Dict[str, Any]:
    """
    Унифицированная фабрика событий.
    Проставляет ts_ms и type, остальное — из payload.
    """
    ev: Dict[str, Any] = {"type": str(type_), "ts_ms": int(time.time() * 1000)}
    for k, v in (payload or {}).items():
        ev[k] = v
    return ev

def get_backpressure_conf(event_type: str) -> Dict[str, Any]:
    return DEFAULT_BACKPRESSURE_MAP.get(event_type, {"policy": "drop_oldest", "max_queue": 2000, "priority": 5})
