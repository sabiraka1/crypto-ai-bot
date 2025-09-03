# src/crypto_ai_bot/core/infrastructure/events/bus.py
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("events.bus")

Handler = Callable[["Event"], Awaitable[None]]


@dataclass(frozen=True)
class Event:
    """
    Ğ¡Ğ¾Ğ±Ñ‹Ñ‚Ğ¸Ğµ ÑˆĞ¸Ğ½Ñ‹: Ğ¼Ğ¸Ğ½Ğ¸Ğ¼Ğ°Ğ»ÑŒĞ½Ñ‹Ğ¹ Ğ¿ĞµÑ€ĞµĞ½Ğ¾ÑĞ¸Ğ¼Ñ‹Ğ¹ Ñ„Ğ¾Ñ€Ğ¼Ğ°Ñ‚.
    topic   â€” ÑÑ‚Ñ€Ğ¾ĞºĞ¾Ğ²Ñ‹Ğ¹ ĞºĞ°Ğ½Ğ°Ğ» (Ğ½Ğ°Ğ¿Ñ€Ğ¸Ğ¼ĞµÑ€, 'orders.executed')
    payload â€” Ğ¿Ñ€Ğ¾Ğ¸Ğ·Ğ²Ğ¾Ğ»ÑŒĞ½Ñ‹Ğ¹ JSON-ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ñ‹Ğ¹ ÑĞ»Ğ¾Ğ²Ğ°Ñ€ÑŒ
    key     â€” Ğ¾Ğ¿Ñ†Ğ¸Ğ¾Ğ½Ğ°Ğ»ÑŒĞ½Ñ‹Ğ¹ ĞºĞ»ÑÑ‡ Ğ¿Ğ°Ñ€Ñ‚Ğ¸Ñ†Ğ¸Ğ¾Ğ½Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ¸Ñ/Ğ¸Ğ´ĞµĞ¼Ğ¿Ğ¾Ñ‚ĞµĞ½Ñ‚Ğ½Ğ¾ÑÑ‚Ğ¸
    ts_ms   â€” Ğ¾Ñ‚Ğ¼ĞµÑ‚ĞºĞ° Ğ²Ñ€ĞµĞ¼ĞµĞ½Ğ¸ Ğ¾Ñ‚Ğ¿Ñ€Ğ°Ğ²ĞºĞ¸ ÑĞ¾Ğ±Ñ‹Ñ‚Ğ¸Ñ
    """
    topic: str
    payload: dict[str, Any]
    key: str | None = None
    ts_ms: int = 0


class AsyncEventBus:
    """
    Ğ›Ñ‘Ğ³ĞºĞ°Ñ Ğ°ÑĞ¸Ğ½Ñ…Ñ€Ğ¾Ğ½Ğ½Ğ°Ñ ÑˆĞ¸Ğ½Ğ° ÑĞ¾Ğ±Ñ‹Ñ‚Ğ¸Ğ¹ Ğ±ĞµĞ· Ğ²Ğ½ĞµÑˆĞ½Ğ¸Ñ… Ğ±Ñ€Ğ¾ĞºĞµÑ€Ğ¾Ğ²:
      - subscribe(topic, handler) / subscribe_dlq(handler)
      - publish(topic, payload, key=None) Ñ Ñ€ĞµÑ‚Ñ€Ğ°ÑĞ¼Ğ¸ Ğ¸ Ğ±ÑĞºĞ¾Ñ„Ñ„Ğ¾Ğ¼
      - Ğ¾Ğ±Ñ€Ğ°Ğ±Ğ¾Ñ‚ĞºĞ° Ğ¾ÑˆĞ¸Ğ±Ğ¾Ğº Ñ‡ĞµÑ€ĞµĞ· DLQ-Ğ¿Ğ¾Ğ´Ğ¿Ğ¸ÑÑ‡Ğ¸ĞºĞ¾Ğ²
    Ğ“Ğ°Ñ€Ğ°Ğ½Ñ‚Ğ¸Ğ¸ Ğ´Ğ¾ÑÑ‚Ğ°Ğ²ĞºĞ¸: at-most-once (in-process).
    """

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        backoff_base_ms: int = 250,
        backoff_factor: float = 2.0,
    ) -> None:
        self.max_attempts = int(max_attempts)
        self.backoff_base_ms = int(backoff_base_ms)
        self.backoff_factor = float(backoff_factor)
        self._subs: defaultdict[str, list[Handler]] = defaultdict(list)
        self._dlq: list[Handler] = []

    # -------------------------
    # ĞŸĞ¾Ğ´Ğ¿Ğ¸ÑĞºĞ¸
    # -------------------------
    def subscribe(self, topic: str, handler: Handler) -> None:
        """ĞŸĞ¾Ğ´Ğ¿Ğ¸ÑĞºĞ° Ğ½Ğ° ĞºĞ¾Ğ½ĞºÑ€ĞµÑ‚Ğ½Ñ‹Ğ¹ topic (Ñ‚Ğ¾Ñ‡Ğ½Ğ¾Ğµ ÑĞ¾Ğ²Ğ¿Ğ°Ğ´ĞµĞ½Ğ¸Ğµ)."""
        self._subs[topic].append(handler)
        _log.info("bus_subscribed", extra={"topic": topic, "handler": getattr(handler, "__name__", "handler")})

    # ĞĞ¾Ğ²Ñ‹Ğ¹ Ğ°Ğ»Ğ¸Ğ°Ñ Ğ´Ğ»Ñ ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ğ¾ÑÑ‚Ğ¸ Ñ EventBusPort Ğ¸ ĞºĞ¾Ğ´Ğ¾Ğ¼, Ğ²Ñ‹Ğ·Ñ‹Ğ²Ğ°ÑÑ‰Ğ¸Ğ¼ bus.on(...)
    def on(self, topic: str, handler: Handler) -> None:
        self.subscribe(topic, handler)

    def subscribe_dlq(self, handler: Handler) -> None:
        """ĞŸĞ¾Ğ´Ğ¿Ğ¸ÑĞºĞ° Ğ½Ğ° DLQ â€” Ğ¿Ğ¾Ğ»ÑƒÑ‡Ğ°ĞµÑ‚ ÑĞ¾Ğ±Ñ‹Ñ‚Ğ¸Ñ, Ğ½Ğµ Ğ´Ğ¾ÑÑ‚Ğ°Ğ²Ğ»ĞµĞ½Ğ½Ñ‹Ğµ Ğ¾Ğ±Ñ€Ğ°Ğ±Ğ¾Ñ‚Ñ‡Ğ¸ĞºĞ°Ğ¼ Ğ¿Ğ¾ÑĞ»Ğµ Ñ€ĞµÑ‚Ñ€Ğ°ĞµĞ²."""
        self._dlq.append(handler)
        _log.info("bus_subscribed_dlq", extra={"handler": getattr(handler, "__name__", "handler")})

    # -------------------------
    # ĞŸÑƒĞ±Ğ»Ğ¸ĞºĞ°Ñ†Ğ¸Ñ
    # -------------------------
    async def publish(self, topic: str, payload: dict[str, Any], *, key: str | None = None) -> dict[str, Any]:
        """
        ĞŸÑƒĞ±Ğ»Ğ¸ĞºĞ°Ñ†Ğ¸Ñ ÑĞ¾Ğ±Ñ‹Ñ‚Ğ¸Ñ Ñ ÑĞ¸Ğ½Ñ…Ñ€Ğ¾Ğ½Ğ½Ğ¾Ğ¹ Ğ´Ğ¾ÑÑ‚Ğ°Ğ²ĞºĞ¾Ğ¹ Ğ»Ğ¾ĞºĞ°Ğ»ÑŒĞ½Ñ‹Ğ¼ Ğ¿Ğ¾Ğ´Ğ¿Ğ¸ÑÑ‡Ğ¸ĞºĞ°Ğ¼.
        Ğ•ÑĞ»Ğ¸ Ğ¾Ğ±Ñ€Ğ°Ğ±Ğ¾Ñ‚Ñ‡Ğ¸Ğº Ğ¿Ğ°Ğ´Ğ°ĞµÑ‚ â€” N Ñ€ĞµÑ‚Ñ€Ğ°ĞµĞ² Ñ ÑĞºÑĞ¿Ğ¾Ğ½ĞµĞ½Ñ†Ğ¸Ğ°Ğ»ÑŒĞ½Ñ‹Ğ¼ Ğ±ÑĞºĞ¾Ñ„Ñ„Ğ¾Ğ¼,
        Ğ·Ğ°Ñ‚ĞµĞ¼ ÑĞ¾Ğ±Ñ‹Ñ‚Ğ¸Ğµ Ğ¾Ñ‚Ğ¿Ñ€Ğ°Ğ²Ğ»ÑĞµÑ‚ÑÑ Ğ² DLQ.
        """
        evt = Event(topic=topic, payload=payload, key=key, ts_ms=now_ms())
        handlers = list(self._subs.get(topic, []))
        if not handlers:
            inc("bus_publish_no_subscribers_total", topic=topic)
            _log.info("bus_published_no_subscribers", extra={"topic": topic})
            return {"ok": True, "delivered": 0, "topic": topic}

        delivered = 0
        for h in handlers:
            attempt = 1
            delay_ms = self.backoff_base_ms
            while True:
                try:
                    await h(evt)  # ĞŸĞµÑ€ĞµĞ´Ğ°ĞµĞ¼ Event, Ğ° Ğ½Ğµ payload
                    delivered += 1
                    inc("bus_handler_ok_total", topic=topic, handler=getattr(h, "__name__", "handler"))
                    break
                except Exception:
                    if attempt >= self.max_attempts:
                        _log.error(
                            "bus_handler_failed",
                            extra={"topic": topic, "handler": getattr(h, "__name__", "handler"), "attempt": attempt},
                            exc_info=True,
                        )
                        inc("bus_handler_failed_total", topic=topic, handler=getattr(h, "__name__", "handler"))
                        await self._emit_to_dlq(evt, failed_handler=getattr(h, "__name__", "handler"))
                        break
                    _log.debug(
                        "bus_handler_retry",
                        extra={"topic": topic, "handler": getattr(h, "__name__", "handler"), "attempt": attempt, "next_delay_ms": delay_ms},
                    )
                    await asyncio.sleep(max(0.001, delay_ms / 1000))
                    attempt += 1
                    delay_ms = int(delay_ms * self.backoff_factor)

        inc("bus_publish_ok_total", topic=topic, delivered=delivered)
        _log.info("bus_published", extra={"topic": topic, "delivered": delivered, "key": key})
        return {"ok": True, "delivered": delivered, "topic": topic}

    # -------------------------
    # ĞœĞµÑ‚Ğ¾Ğ´Ñ‹ Ğ´Ğ»Ñ ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ğ¾ÑÑ‚Ğ¸ Ñ Ğ¿Ñ€Ğ¾Ñ‚Ğ¾ĞºĞ¾Ğ»Ğ¾Ğ¼
    # -------------------------
    async def start(self) -> None:
        """Ğ”Ğ»Ñ ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ğ¾ÑÑ‚Ğ¸ Ñ EventBusPort"""
        pass

    async def close(self) -> None:
        """Ğ”Ğ»Ñ ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ğ¾ÑÑ‚Ğ¸ Ñ EventBusPort"""
        pass

    # -------------------------
    # Ğ’Ğ½ÑƒÑ‚Ñ€ĞµĞ½Ğ½ĞµĞµ: Ğ¾Ñ‚Ğ¿Ñ€Ğ°Ğ²ĞºĞ° Ğ² DLQ
    # -------------------------
    async def _emit_to_dlq(self, evt: Event, *, failed_handler: str) -> None:
        if not self._dlq:
            return
        dlq_evt = Event(
            topic="__dlq__",
            payload={"original_topic": evt.topic, "failed_handler": failed_handler, **evt.payload},
            key=evt.key,
            ts_ms=now_ms(),
        )
        for d in self._dlq:
            try:
                await d(dlq_evt)
                inc("bus_dlq_delivered_total", original_topic=evt.topic)
            except Exception:
                _log.debug("bus_dlq_handler_failed", extra={"original_topic": evt.topic}, exc_info=True)

    # -------------------------
    # Ğ£Ñ‚Ğ¸Ğ»Ğ¸Ñ‚Ñ‹ Ğ´Ğ»Ñ Ğ¿Ñ€Ğ¾ÑÑ‚Ğ¾Ğ³Ğ¾ Ğ¿Ğ¾Ğ´ĞºĞ»ÑÑ‡ĞµĞ½Ğ¸Ñ
    # -------------------------
    def attach_logger_dlq(self) -> None:
        """Ğ’ĞºĞ»ÑÑ‡Ğ¸Ñ‚ÑŒ Ğ´ĞµÑ„Ğ¾Ğ»Ñ‚Ğ½Ñ‹Ğ¹ DLQ-Ğ»Ğ¾Ğ³Ğ³ĞµÑ€, ĞµÑĞ»Ğ¸ ÑĞ²Ğ¾Ğ¸Ñ… Ğ¿Ğ¾Ğ´Ğ¿Ğ¸ÑÑ‡Ğ¸ĞºĞ¾Ğ² Ğ½ĞµÑ‚."""
        async def _log_dlq(e: Event) -> None:
            _log.error("DLQ", extra={"topic": e.payload.get("original_topic"), "payload": e.payload})
        if not self._dlq:
            self.subscribe_dlq(_log_dlq)
