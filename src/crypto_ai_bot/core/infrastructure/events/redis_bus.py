from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import suppress
import json
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

Handler = Callable[[dict[str, Any]], Awaitable[None]]
_log = get_logger("events.redis")


class RedisEventBus:
    """
    Asynchronous event bus on Redis Pub/Sub.
    publish(topic: str, payload: dict) -> None
    on(topic: str, handler: Callable[[dict], Awaitable[None]]) -> None
    start()/close() - lifecycle management.
    """

    def __init__(self, url: str, *, ping_interval_sec: float = 30.0) -> None:
        if not url:
            raise ValueError("RedisEventBus requires non-empty redis url (e.g. redis://...)")
        self._url = url
        self._r: Redis | None = None
        self._ps: PubSub | None = None
        self._task: asyncio.Task[None] | None = None
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._topics: set[str] = set()
        self._ping_interval = ping_interval_sec
        self._started = False

    async def start(self) -> None:
        """Start the event bus."""
        if self._started:
            return
        self._r = Redis.from_url(self._url, encoding="utf-8", decode_responses=True)
        self._ps = self._r.pubsub()
        if self._topics:
            await self._ps.subscribe(*self._topics)
        self._task = asyncio.create_task(self._listen_loop())
        self._started = True
        _log.info("redis_bus_started", extra={"url": self._url})

    async def close(self) -> None:
        """Close the event bus."""
        self._started = False

        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        if self._ps:
            with suppress(Exception):
                await self._ps.close()
            self._ps = None

        if self._r:
            with suppress(Exception):
                await self._r.close()
            self._r = None

        _log.info("redis_bus_closed")

    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None:
        """Publish event to topic."""
        if not isinstance(payload, dict):
            raise TypeError("payload must be dict")

        if not self._r:
            # Allow publish before start(): lazy init client
            self._r = Redis.from_url(self._url, encoding="utf-8", decode_responses=True)

        msg = {"key": key, "payload": payload}
        data = json.dumps(msg, ensure_ascii=False)

        try:
            await self._r.publish(topic, data)
            inc("bus_publish_total", topic=topic)
        except Exception:
            _log.error("redis_publish_failed", extra={"topic": topic}, exc_info=True)

    def on(self, topic: str, handler: Handler) -> None:
        """Subscribe to topic with handler."""
        self._handlers[topic].append(handler)
        self._topics.add(topic)

        # If already started - subscribe immediately
        if self._started and self._ps:
            asyncio.create_task(self._ps.subscribe(topic))

    async def _listen_loop(self) -> None:
        """Main listening loop."""
        assert self._ps is not None
        last_ping = 0.0

        try:
            while True:
                # Ping periodically to keep connection alive
                if self._r and (self._ping_interval > 0):
                    now = asyncio.get_event_loop().time()
                    if now - last_ping > self._ping_interval:
                        try:
                            await self._r.ping()
                        except Exception:
                            _log.warning("redis_ping_failed", exc_info=True)
                        last_ping = now

                msg = await self._ps.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not msg:
                    await asyncio.sleep(0.05)
                    continue

                topic = str(msg.get("channel", "") or "")
                raw = msg.get("data", "")

                try:
                    obj = json.loads(raw) if isinstance(raw, str) and raw else {}
                except Exception:
                    obj = {}

                payload = obj.get("payload", {}) if isinstance(obj, dict) else {}

                # Call handlers
                for handler in list(self._handlers.get(topic, [])):
                    try:
                        await handler(payload)
                    except Exception:
                        _log.error("handler_failed", extra={"topic": topic}, exc_info=True)
                        inc("bus_handler_errors_total", topic=topic)

        except asyncio.CancelledError:
            pass
        except Exception:
            _log.error("redis_listen_loop_crashed", exc_info=True)
