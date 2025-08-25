from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Callable, Awaitable, DefaultDict
from collections import defaultdict

from ...utils.logging import get_logger
from ...utils.metrics import inc, timer

_LOG = get_logger("event.bus")


@dataclass
class AsyncEventBus:
    max_attempts: int = 3
    backoff_base_ms: int = 250
    backoff_factor: float = 2.0

    _subs: DefaultDict[str, list[Callable[[dict], Awaitable[None]]]] = field(default_factory=lambda: defaultdict(list))

    def subscribe(self, topic: str, handler: Callable[[dict], Awaitable[None]]) -> None:
        self._subs[topic].append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any], *, key: str | None = None) -> None:
        """Fire-and-forget публикация. Обработчики выполняются последовательно.
        Ошибки логируем, метрики пишем. Повторные попытки — ответственность обработчиков/внешнего ретрая.
        """
        inc("events_total", {"topic": topic})
        handlers = self._subs.get(topic, [])
        if not handlers:
            return
        for h in handlers:
            attempts = 0
            while True:
                attempts += 1
                try:
                    with timer("event_handler_ms", {"topic": topic}):
                        await h(payload)
                    break
                except Exception as exc:
                    _LOG.error("handler_failed", extra={"topic": topic, "error": str(exc), "attempt": attempts})
                    if attempts >= self.max_attempts:
                        break
                    await asyncio.sleep((self.backoff_base_ms * (self.backoff_factor ** (attempts - 1))) / 1000.0)