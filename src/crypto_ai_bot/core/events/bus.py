# src/crypto_ai_bot/core/events/bus.py
from __future__ import annotations
import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Tuple
from ..settings import settings as _cfg  # если у вас другой путь — поправьте
from ...utils.metrics import metrics

Subscriber = Callable[[str, Dict[str, Any]], Awaitable[None]]

class AsyncEventBus:
    def __init__(self) -> None:
        self._subs: Dict[str, List[Subscriber]] = {}
        self._lock = asyncio.Lock()
        self.m_published = metrics.counter("bus_published_total", "Total events published", ["topic"])
        self.m_failed    = metrics.counter("bus_publish_failed_total", "Total publish failures", ["topic"])

    async def subscribe(self, topic: str, handler: Subscriber) -> None:
        async with self._lock:
            self._subs.setdefault(topic, []).append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        subs = list(self._subs.get(topic, []))
        self.m_published.labels(topic).inc()
        for h in subs:
            try:
                await h(topic, payload)
            except Exception as e:
                self.m_failed.labels(topic).inc()
                # DLQ как отдельная тема
                if topic != "dlq.error":
                    await self.publish("dlq.error", {"cause": topic, "error": str(e), "payload": payload})

# singleton-провайдер
_global_bus: AsyncEventBus | None = None

def get_event_bus() -> AsyncEventBus:
    global _global_bus
    if _global_bus is None:
        _global_bus = AsyncEventBus()
    return _global_bus
