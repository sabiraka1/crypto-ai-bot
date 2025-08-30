from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, Optional

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("events.redis")


class RedisEventBus:
    """
    Durable pub/sub через Redis. Совместим по API с AsyncEventBus: publish(), subscribe()/on().
    """

    def __init__(self, url: str, *, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.url = url
        self._loop = loop or asyncio.get_event_loop()
        self._redis = None
        self._pub = None
        self._sub = None
        self._subs: Dict[str, Callable[[dict], Awaitable[None]]] = {}
        self._task: Optional[asyncio.Task] = None
        self._stopping = False

    async def start(self) -> None:
        try:
            import redis.asyncio as redis  # type: ignore
        except Exception as exc:
            raise RuntimeError("redis-py is not installed. pip install redis>=4") from exc

        self._redis = redis.from_url(self.url, decode_responses=True)
        self._pub = self._redis
        self._sub = self._redis.pubsub()
        self._stopping = False
        self._task = self._loop.create_task(self._worker(), name="redis-bus-worker")
        _log.info("redis_event_bus_started", extra={"url": self.url})

    async def close(self) -> None:
        self._stopping = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
        try:
            if self._sub:
                await self._sub.close()
        except Exception:
            pass
        try:
            if self._redis:
                await self._redis.close()
        except Exception:
            pass
        _log.info("redis_event_bus_closed")

    def subscribe(self, topic: str, coro: Callable[[dict], Awaitable[None]]) -> None:
        self._subs[topic] = coro

    def on(self, topic: str, coro: Callable[[dict], Awaitable[None]]) -> None:
        self.subscribe(topic, coro)

    async def publish(self, topic: str, payload: Dict[str, Any], key: Optional[str] = None) -> None:
        if not self._pub:
            _log.warning("redis_bus_not_started_fallback_noop", extra={"topic": topic})
            return
        msg = json.dumps({"topic": topic, "key": key, "payload": payload}, ensure_ascii=False)
        try:
            await self._pub.publish(topic, msg)
        except Exception as exc:
            _log.error("redis_publish_failed", extra={"topic": topic, "error": str(exc)})

    async def _worker(self) -> None:
        assert self._sub is not None
        if self._subs:
            await self._sub.subscribe(*list(self._subs.keys()))
        while not self._stopping:
            try:
                raw = await self._sub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not raw:
                    await asyncio.sleep(0.05)
                    continue
                topic = raw.get("channel")
                data = raw.get("data")
                if not topic or not data:
                    continue
                try:
                    obj = json.loads(data)
                    evt = obj.get("payload") or {}
                except Exception:
                    evt = {}
                handler = self._subs.get(topic)
                if handler:
                    try:
                        await handler(evt)
                    except Exception as exc:
                        _log.error("redis_handler_failed", extra={"topic": topic, "error": str(exc)})
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _log.error("redis_worker_error", extra={"error": str(exc)})
                await asyncio.sleep(0.2)
