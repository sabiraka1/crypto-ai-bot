# src/crypto_ai_bot/core/events/factory.py
from __future__ import annotations
from typing import Any, Dict, Optional

# Карта backpressure по типам событий: стратегия и лимит очереди.
# Можно переопределить через CFG.EVENTS_BACKPRESSURE_JSON (если захочешь).
DEFAULT_BACKPRESSURE_MAP: Dict[str, Dict[str, Any]] = {
    "DecisionEvaluated": {"strategy": "keep_latest", "queue_size": 1024},
    "OrderExecuted":     {"strategy": "drop_oldest", "queue_size": 2048},
    "OrderFailed":       {"strategy": "drop_oldest", "queue_size": 2048},
    "FlowFinished":      {"strategy": "keep_latest", "queue_size": 1024},
}

def build_sync_bus(cfg: Any, repos: Any) -> Any:
    from .bus import EventBus
    dlq_max = int(getattr(cfg, "BUS_DLQ_MAX", 1000))
    return EventBus(dlq_max=dlq_max)

def build_async_bus(cfg: Any, repos: Any) -> Any:
    from .async_bus import AsyncEventBus
    dlq_max = int(getattr(cfg, "BUS_DLQ_MAX", 1000))
    return AsyncEventBus(strategy_map=DEFAULT_BACKPRESSURE_MAP, dlq_max=dlq_max)
