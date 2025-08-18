# src/crypto_ai_bot/app/bus_wiring.py
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from crypto_ai_bot.core.events.bus import AsyncEventBus

logger = logging.getLogger("app.bus")

Handler = Callable[[str, Dict[str, Any]], Awaitable[None]]


class BusContainer:
    """
    Тонкая обёртка над AsyncEventBus:
      - start()/stop() для lifecycle
      - subscribe()/publish()
      - health() для /health
    """
    def __init__(self, *, max_queue: int = 1000, concurrency: int = 8) -> None:
        self._bus = AsyncEventBus(max_queue=max_queue, concurrency=concurrency)

    async def start(self) -> None:
        await self._bus.start()

    async def stop(self) -> None:
        await self._bus.stop()

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._bus.subscribe(topic, handler)

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        await self._bus.publish(topic, payload)

    def health(self) -> Dict[str, Any]:
        return self._bus.health()
