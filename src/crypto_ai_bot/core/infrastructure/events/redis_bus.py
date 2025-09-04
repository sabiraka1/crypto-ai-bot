from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
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
    Асинхронная шина на Redis Pub/Sub.
    publish(topic: str, payload: dict) -> None
    on(topic: str, handler: Callable[[dict], Awaitable[None]]) -> None
    start()/close() — управление жизненным циклом подписки.
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
        self._started = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
            self._task = None
        if self._ps:
            try:
                await self._ps.close()
            except Exception:
                pass
            self._ps = None
        if self._r:
            try:
                await self._r.close()
            except Exception:
                pass
            self._r = None
        _log.info("redis_bus_closed")

    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None:
        if not isinstance(payload, dict):
            raise TypeError("payload must be dict")
        if not self._r:
            # позволяем publish до start(): лениво инициализируем клиент
            self._r = Redis.from_url(self._url, encoding="utf-8", decode_responses=True)
        msg = {"key": key, "payload": payload}
        data = json.dumps(msg, ensure_ascii=False)
        try:
            await self._r.publish(topic, data)
            inc("bus_publish_total", topic=topic)
        except Exception:
            _log.error("redis_publish_failed", extra={"topic": topic}, exc_info=True)

    def on(self, topic: str, handler: Handler) -> None:
        self._handlers[topic].append(handler)
        self._topics.add(topic)
        # если уже запущены — подписываемся немедленно
        if self._started and self._ps:
            asyncio.create_task(self._ps.subscribe(topic))

    async def _listen_loop(self) -> None:
        assert self._ps is not None
        last_ping = 0.0
        try:
            while True:
                # ping каждые N сек, чтобы поддерживать соединение
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

                for h in list(self._handlers.get(topic, [])):
                    try:
                        await h(payload)
                    except Exception:
                        _log.error("handler_failed", extra={"topic": topic}, exc_info=True)
                        inc("bus_handler_errors_total", topic=topic)
        except asyncio.CancelledError:
            pass
        except Exception:
            _log.error("redis_listen_loop_crashed", exc_info=True)
