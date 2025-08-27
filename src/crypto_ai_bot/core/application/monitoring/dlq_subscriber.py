from __future__ import annotations

from typing import Optional, Dict, Any

from ..events.bus import AsyncEventBus, Event
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc


_log = get_logger("monitoring.dlq")


async def _dlq_logger(event: Event) -> None:
    """
    Базовый подписчик DLQ: шлёт метрику и пишет в лог.
    Никакой логики повторной обработки тут нет — это просто наблюдаемость.
    """
    payload: Dict[str, Any] = event.payload or {}
    topic = payload.get("original_topic", "unknown")
    handler = payload.get("handler", "unknown")
    error = payload.get("error", "unknown")

    inc("events_dlq_total", {"original_topic": topic, "handler": handler})
    _log.error(
        "event_dlq",
        extra={
            "original_topic": topic,
            "handler": handler,
            "error": error,
            "payload_keys": list(payload.keys()),
        },
    )


def attach(bus: AsyncEventBus) -> None:
    """
    Подключить базовый DLQ-логгер к шине.
    Вызывать один раз после инициализации EventBus.
    """
    try:
        bus.subscribe_dlq(_dlq_logger)
        _log.info("dlq_logger_attached")
    except Exception as exc:
        _log.error("dlq_logger_attach_failed", extra={"error": str(exc)})
