from .async_bus import AsyncBus, EventPriority, DEFAULT_BACKPRESSURE

# Recommended defaults per event-domain (can be overridden in Settings)
DEFAULT_BACKPRESSURE_MAP = {
    "orders.*": "keep_latest",   # не копим очереди команд, новое важнее старого
    "metrics.*": "drop_oldest",  # метрики лучше не блокировать, теряем самые старые
    "audit.*": "block",          # аудит нельзя терять — блокируем издателя
}

__all__ = ["AsyncBus", "EventPriority", "DEFAULT_BACKPRESSURE", "DEFAULT_BACKPRESSURE_MAP"]
