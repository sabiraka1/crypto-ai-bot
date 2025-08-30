from __future__ import annotations

from typing import Awaitable, Callable, Optional

from crypto_ai_bot.core.application.ports import EventBusPort
from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("monitoring.dlq")


async def _default_handler(evt: dict) -> None:
    _log.error("dlq_event", extra={"event": evt})
    inc("dlq.events", {"ok": "0"})


def attach_dlq_subscriber(bus: EventBusPort, handler: Optional[Callable[[dict], Awaitable[None]]] = None) -> None:
    async def _handle(evt: dict) -> None:
        try:
            if handler:
                await handler(evt)
            else:
                await _default_handler(evt)
        except Exception as e:
            _log.error("dlq_handler_failed", extra={"error": str(e)})
            inc("dlq.events", {"ok": "0", "err": "1"})
    bus.on("dlq", _handle)
