from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional, Callable, Awaitable, DefaultDict, List
from collections import defaultdict

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("events.bus")


@dataclass(frozen=True)
class Event:
    topic: str
    payload: Dict[str, Any]
    key: Optional[str] = None
    ts_ms: int = 0


@dataclass
class AsyncEventBus:
    """Простая асинхронная «шина событий» с ретраями, подписками и DLQ (in-memory)."""

    max_attempts: int = 3
    backoff_base_ms: int = 250
    backoff_factor: float = 2.0

    def __post_init__(self) -> None:
        self._subs: DefaultDict[str, List[Callable[[Event], Awaitable[None]]]] = defaultdict(list)
        self._dlq: List[Callable[[Event], Awaitable[None]]] = []

    def subscribe(self, topic: str, handler: Callable[[Event], Awaitable[None]]) -> None:
        self._subs[topic].append(handler)

    def subscribe_dlq(self, handler: Callable[[Event], Awaitable[None]]) -> None:
        self._dlq.append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any], *, key: Optional[str] = None) -> Dict[str, Any]:
        attempt = 1
        delay_ms = self.backoff_base_ms
        evt = Event(topic=topic, payload=payload, key=key, ts_ms=now_ms())
        while True:
            try:
                _log.info("bus_publish", extra={"topic": topic, "key": key, "ts_ms": evt.ts_ms})
                # доставить локальным подписчикам (если есть)
                for h in list(self._subs.get(topic, [])):
                    try:
                        await h(evt)
                    except Exception as exc:
                        # уводим событие в DLQ
                        for d in list(self._dlq):
                            try:
                                await d(Event(topic="__dlq__", payload={"original_topic": topic, "handler": getattr(h, "__name__", "?"), "error": str(exc), **payload}, key=key, ts_ms=now_ms()))
                            except Exception:
                                pass
                # no-op producer (место для Kafka/NATS/Redis)
                return {"ok": True, "topic": topic, "key": key}
            except Exception as exc:
                if attempt >= self.max_attempts:
                    _log.error("bus_publish_failed", extra={"topic": topic, "key": key, "error": str(exc)})
                    return {"ok": False, "error": str(exc)}
                await asyncio.sleep(max(0.001, delay_ms / 1000))
                attempt += 1
                delay_ms = int(delay_ms * self.backoff_factor)
