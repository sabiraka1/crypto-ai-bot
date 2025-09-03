# src/crypto_ai_bot/core/infrastructure/events/bus.py
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("events.bus")

Handler = Callable[["Event"], Awaitable[None]]


@dataclass(frozen=True)
class Event:
    """
    ДћВЎДћВѕДћВ±Г‘вЂ№Г‘вЂљДћВёДћВµ Г‘Л†ДћВёДћВЅГ‘вЂ№: ДћВјДћВёДћВЅДћВёДћВјДћВ°ДћВ»Г‘Е’ДћВЅГ‘вЂ№ДћВ№ ДћВїДћВµГ‘в‚¬ДћВµДћВЅДћВѕГ‘ВЃДћВёДћВјГ‘вЂ№ДћВ№ Г‘вЂћДћВѕГ‘в‚¬ДћВјДћВ°Г‘вЂљ.
    topic   Гўв‚¬вЂќ Г‘ВЃГ‘вЂљГ‘в‚¬ДћВѕДћВєДћВѕДћВІГ‘вЂ№ДћВ№ ДћВєДћВ°ДћВЅДћВ°ДћВ» (ДћВЅДћВ°ДћВїГ‘в‚¬ДћВёДћВјДћВµГ‘в‚¬, 'orders.executed')
    payload Гўв‚¬вЂќ ДћВїГ‘в‚¬ДћВѕДћВёДћВ·ДћВІДћВѕДћВ»Г‘Е’ДћВЅГ‘вЂ№ДћВ№ JSON-Г‘ВЃДћВѕДћВІДћВјДћВµГ‘ВЃГ‘вЂљДћВёДћВјГ‘вЂ№ДћВ№ Г‘ВЃДћВ»ДћВѕДћВІДћВ°Г‘в‚¬Г‘Е’
    key     Гўв‚¬вЂќ ДћВѕДћВїГ‘вЂ ДћВёДћВѕДћВЅДћВ°ДћВ»Г‘Е’ДћВЅГ‘вЂ№ДћВ№ ДћВєДћВ»Г‘ВЋГ‘вЂЎ ДћВїДћВ°Г‘в‚¬Г‘вЂљДћВёГ‘вЂ ДћВёДћВѕДћВЅДћВёГ‘в‚¬ДћВѕДћВІДћВ°ДћВЅДћВёГ‘ВЏ/ДћВёДћВґДћВµДћВјДћВїДћВѕГ‘вЂљДћВµДћВЅГ‘вЂљДћВЅДћВѕГ‘ВЃГ‘вЂљДћВё
    ts_ms   Гўв‚¬вЂќ ДћВѕГ‘вЂљДћВјДћВµГ‘вЂљДћВєДћВ° ДћВІГ‘в‚¬ДћВµДћВјДћВµДћВЅДћВё ДћВѕГ‘вЂљДћВїГ‘в‚¬ДћВ°ДћВІДћВєДћВё Г‘ВЃДћВѕДћВ±Г‘вЂ№Г‘вЂљДћВёГ‘ВЏ
    """

    topic: str
    payload: dict[str, Any]
    key: str | None = None
    ts_ms: int = 0


class AsyncEventBus:
    """
    ДћвЂєГ‘вЂДћВіДћВєДћВ°Г‘ВЏ ДћВ°Г‘ВЃДћВёДћВЅГ‘вЂ¦Г‘в‚¬ДћВѕДћВЅДћВЅДћВ°Г‘ВЏ Г‘Л†ДћВёДћВЅДћВ° Г‘ВЃДћВѕДћВ±Г‘вЂ№Г‘вЂљДћВёДћВ№ ДћВ±ДћВµДћВ· ДћВІДћВЅДћВµГ‘Л†ДћВЅДћВёГ‘вЂ¦ ДћВ±Г‘в‚¬ДћВѕДћВєДћВµГ‘в‚¬ДћВѕДћВІ:
      - subscribe(topic, handler) / subscribe_dlq(handler)
      - publish(topic, payload, key=None) Г‘ВЃ Г‘в‚¬ДћВµГ‘вЂљГ‘в‚¬ДћВ°Г‘ВЏДћВјДћВё ДћВё ДћВ±Г‘ВЌДћВєДћВѕГ‘вЂћГ‘вЂћДћВѕДћВј
      - ДћВѕДћВ±Г‘в‚¬ДћВ°ДћВ±ДћВѕГ‘вЂљДћВєДћВ° ДћВѕГ‘Л†ДћВёДћВ±ДћВѕДћВє Г‘вЂЎДћВµГ‘в‚¬ДћВµДћВ· DLQ-ДћВїДћВѕДћВґДћВїДћВёГ‘ВЃГ‘вЂЎДћВёДћВєДћВѕДћВІ
    ДћвЂњДћВ°Г‘в‚¬ДћВ°ДћВЅГ‘вЂљДћВёДћВё ДћВґДћВѕГ‘ВЃГ‘вЂљДћВ°ДћВІДћВєДћВё: at-most-once (in-process).
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
    # ДћЕёДћВѕДћВґДћВїДћВёГ‘ВЃДћВєДћВё
    # -------------------------
    def subscribe(self, topic: str, handler: Handler) -> None:
        """ДћЕёДћВѕДћВґДћВїДћВёГ‘ВЃДћВєДћВ° ДћВЅДћВ° ДћВєДћВѕДћВЅДћВєГ‘в‚¬ДћВµГ‘вЂљДћВЅГ‘вЂ№ДћВ№ topic (Г‘вЂљДћВѕГ‘вЂЎДћВЅДћВѕДћВµ Г‘ВЃДћВѕДћВІДћВїДћВ°ДћВґДћВµДћВЅДћВёДћВµ)."""
        self._subs[topic].append(handler)
        _log.info(
            "bus_subscribed", extra={"topic": topic, "handler": getattr(handler, "__name__", "handler")}
        )

    # ДћВќДћВѕДћВІГ‘вЂ№ДћВ№ ДћВ°ДћВ»ДћВёДћВ°Г‘ВЃ ДћВґДћВ»Г‘ВЏ Г‘ВЃДћВѕДћВІДћВјДћВµГ‘ВЃГ‘вЂљДћВёДћВјДћВѕГ‘ВЃГ‘вЂљДћВё Г‘ВЃ EventBusPort ДћВё ДћВєДћВѕДћВґДћВѕДћВј, ДћВІГ‘вЂ№ДћВ·Г‘вЂ№ДћВІДћВ°Г‘ВЋГ‘вЂ°ДћВёДћВј bus.on(...)
    def on(self, topic: str, handler: Handler) -> None:
        self.subscribe(topic, handler)

    def subscribe_dlq(self, handler: Handler) -> None:
        """ДћЕёДћВѕДћВґДћВїДћВёГ‘ВЃДћВєДћВ° ДћВЅДћВ° DLQ Гўв‚¬вЂќ ДћВїДћВѕДћВ»Г‘Ж’Г‘вЂЎДћВ°ДћВµГ‘вЂљ Г‘ВЃДћВѕДћВ±Г‘вЂ№Г‘вЂљДћВёГ‘ВЏ, ДћВЅДћВµ ДћВґДћВѕГ‘ВЃГ‘вЂљДћВ°ДћВІДћВ»ДћВµДћВЅДћВЅГ‘вЂ№ДћВµ ДћВѕДћВ±Г‘в‚¬ДћВ°ДћВ±ДћВѕГ‘вЂљГ‘вЂЎДћВёДћВєДћВ°ДћВј ДћВїДћВѕГ‘ВЃДћВ»ДћВµ Г‘в‚¬ДћВµГ‘вЂљГ‘в‚¬ДћВ°ДћВµДћВІ."""
        self._dlq.append(handler)
        _log.info("bus_subscribed_dlq", extra={"handler": getattr(handler, "__name__", "handler")})

    # -------------------------
    # ДћЕёГ‘Ж’ДћВ±ДћВ»ДћВёДћВєДћВ°Г‘вЂ ДћВёГ‘ВЏ
    # -------------------------
    async def publish(self, topic: str, payload: dict[str, Any], *, key: str | None = None) -> dict[str, Any]:
        """
        ДћЕёГ‘Ж’ДћВ±ДћВ»ДћВёДћВєДћВ°Г‘вЂ ДћВёГ‘ВЏ Г‘ВЃДћВѕДћВ±Г‘вЂ№Г‘вЂљДћВёГ‘ВЏ Г‘ВЃ Г‘ВЃДћВёДћВЅГ‘вЂ¦Г‘в‚¬ДћВѕДћВЅДћВЅДћВѕДћВ№ ДћВґДћВѕГ‘ВЃГ‘вЂљДћВ°ДћВІДћВєДћВѕДћВ№ ДћВ»ДћВѕДћВєДћВ°ДћВ»Г‘Е’ДћВЅГ‘вЂ№ДћВј ДћВїДћВѕДћВґДћВїДћВёГ‘ВЃГ‘вЂЎДћВёДћВєДћВ°ДћВј.
        ДћвЂўГ‘ВЃДћВ»ДћВё ДћВѕДћВ±Г‘в‚¬ДћВ°ДћВ±ДћВѕГ‘вЂљГ‘вЂЎДћВёДћВє ДћВїДћВ°ДћВґДћВ°ДћВµГ‘вЂљ Гўв‚¬вЂќ N Г‘в‚¬ДћВµГ‘вЂљГ‘в‚¬ДћВ°ДћВµДћВІ Г‘ВЃ Г‘ВЌДћВєГ‘ВЃДћВїДћВѕДћВЅДћВµДћВЅГ‘вЂ ДћВёДћВ°ДћВ»Г‘Е’ДћВЅГ‘вЂ№ДћВј ДћВ±Г‘ВЌДћВєДћВѕГ‘вЂћГ‘вЂћДћВѕДћВј,
        ДћВ·ДћВ°Г‘вЂљДћВµДћВј Г‘ВЃДћВѕДћВ±Г‘вЂ№Г‘вЂљДћВёДћВµ ДћВѕГ‘вЂљДћВїГ‘в‚¬ДћВ°ДћВІДћВ»Г‘ВЏДћВµГ‘вЂљГ‘ВЃГ‘ВЏ ДћВІ DLQ.
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
                    await h(evt)  # ДћЕёДћВµГ‘в‚¬ДћВµДћВґДћВ°ДћВµДћВј Event, ДћВ° ДћВЅДћВµ payload
                    delivered += 1
                    inc("bus_handler_ok_total", topic=topic, handler=getattr(h, "__name__", "handler"))
                    break
                except Exception:
                    if attempt >= self.max_attempts:
                        _log.error(
                            "bus_handler_failed",
                            extra={
                                "topic": topic,
                                "handler": getattr(h, "__name__", "handler"),
                                "attempt": attempt,
                            },
                            exc_info=True,
                        )
                        inc(
                            "bus_handler_failed_total", topic=topic, handler=getattr(h, "__name__", "handler")
                        )
                        await self._emit_to_dlq(evt, failed_handler=getattr(h, "__name__", "handler"))
                        break
                    _log.debug(
                        "bus_handler_retry",
                        extra={
                            "topic": topic,
                            "handler": getattr(h, "__name__", "handler"),
                            "attempt": attempt,
                            "next_delay_ms": delay_ms,
                        },
                    )
                    await asyncio.sleep(max(0.001, delay_ms / 1000))
                    attempt += 1
                    delay_ms = int(delay_ms * self.backoff_factor)

        inc("bus_publish_ok_total", topic=topic, delivered=delivered)
        _log.info("bus_published", extra={"topic": topic, "delivered": delivered, "key": key})
        return {"ok": True, "delivered": delivered, "topic": topic}

    # -------------------------
    # ДћЕ“ДћВµГ‘вЂљДћВѕДћВґГ‘вЂ№ ДћВґДћВ»Г‘ВЏ Г‘ВЃДћВѕДћВІДћВјДћВµГ‘ВЃГ‘вЂљДћВёДћВјДћВѕГ‘ВЃГ‘вЂљДћВё Г‘ВЃ ДћВїГ‘в‚¬ДћВѕГ‘вЂљДћВѕДћВєДћВѕДћВ»ДћВѕДћВј
    # -------------------------
    async def start(self) -> None:
        """ДћвЂќДћВ»Г‘ВЏ Г‘ВЃДћВѕДћВІДћВјДћВµГ‘ВЃГ‘вЂљДћВёДћВјДћВѕГ‘ВЃГ‘вЂљДћВё Г‘ВЃ EventBusPort"""
        pass

    async def close(self) -> None:
        """ДћвЂќДћВ»Г‘ВЏ Г‘ВЃДћВѕДћВІДћВјДћВµГ‘ВЃГ‘вЂљДћВёДћВјДћВѕГ‘ВЃГ‘вЂљДћВё Г‘ВЃ EventBusPort"""
        pass

    # -------------------------
    # ДћвЂ™ДћВЅГ‘Ж’Г‘вЂљГ‘в‚¬ДћВµДћВЅДћВЅДћВµДћВµ: ДћВѕГ‘вЂљДћВїГ‘в‚¬ДћВ°ДћВІДћВєДћВ° ДћВІ DLQ
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
    # ДћВЈГ‘вЂљДћВёДћВ»ДћВёГ‘вЂљГ‘вЂ№ ДћВґДћВ»Г‘ВЏ ДћВїГ‘в‚¬ДћВѕГ‘ВЃГ‘вЂљДћВѕДћВіДћВѕ ДћВїДћВѕДћВґДћВєДћВ»Г‘ВЋГ‘вЂЎДћВµДћВЅДћВёГ‘ВЏ
    # -------------------------
    def attach_logger_dlq(self) -> None:
        """ДћвЂ™ДћВєДћВ»Г‘ВЋГ‘вЂЎДћВёГ‘вЂљГ‘Е’ ДћВґДћВµГ‘вЂћДћВѕДћВ»Г‘вЂљДћВЅГ‘вЂ№ДћВ№ DLQ-ДћВ»ДћВѕДћВіДћВіДћВµГ‘в‚¬, ДћВµГ‘ВЃДћВ»ДћВё Г‘ВЃДћВІДћВѕДћВёГ‘вЂ¦ ДћВїДћВѕДћВґДћВїДћВёГ‘ВЃГ‘вЂЎДћВёДћВєДћВѕДћВІ ДћВЅДћВµГ‘вЂљ."""

        async def _log_dlq(e: Event) -> None:
            _log.error("DLQ", extra={"topic": e.payload.get("original_topic"), "payload": e.payload})

        if not self._dlq:
            self.subscribe_dlq(_log_dlq)
