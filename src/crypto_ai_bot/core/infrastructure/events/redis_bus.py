# src/crypto_ai_bot/core/infrastructure/events/redis_bus.py
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, DefaultDict, Dict, List, Optional
from collections import defaultdict

try:
    from redis.asyncio import Redis
except Exception as exc:  # pragma: no cover
    raise RuntimeError("redis.asyncio is required for RedisEventBus") from exc

try:
    from crypto_ai_bot.utils.logging import get_logger
except Exception:  # pragma: no cover
    import logging
    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

try:
    from crypto_ai_bot.utils.metrics import inc, observe
except Exception:  # pragma: no cover
    def inc(_name: str, **_labels: Any) -> None:
        pass
    def observe(_name: str, _value: float, _labels: Optional[Dict[str, str]] = None) -> None:
        pass

_log = get_logger("events.redis_bus")

Handler = Callable[[Any], Awaitable[None]]


class RedisEventBus:
    """
    Durable event bus поверх Redis Pub/Sub.
    Хранит реестр подписок и пере-подписывается при старте/реконнекте.
    Формат сообщения: {"topic": "...", "payload": {...}, "ts_ms": int, "key": str?}
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._redis: Optional[Redis] = None
        self._pub: Optional[Redis] = None
        self._subs: DefaultDict[str, List[Handler]] = defaultdict(list)
        self._dlq: List[Handler] = []
        self._listener_task: Optional[asyncio.Task] = None
        self._started: bool = False
        self._active_pubsub = None  # type: ignore

    # ------------------ API совместимый с AsyncEventBus ------------------

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    def on(self, topic: str, handler: Handler) -> None:
        self.subscribe(topic, handler)

    def subscribe_dlq(self, handler: Handler) -> None:
        self._dlq.append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any], *, key: Optional[str] = None) -> Dict[str, Any]:
        if not self._pub:
            raise RuntimeError("RedisEventBus not started")
        msg = json.dumps({"topic": topic, "payload": payload, "key": key})
        ch = f"evt:{topic}"
        t0 = asyncio.get_event_loop().time()
        await self._pub.publish(ch, msg)
        dt_ms = (asyncio.get_event_loop().time() - t0) * 1000.0
        observe("redis_bus.publish.ms", dt_ms, {"topic": topic})
        inc("redis_bus_publish_total", topic=topic)
        return {"ok": True, "topic": topic}

    async def start(self) -> None:
        if self._started:
            return
        self._redis = Redis.from_url(self._url, decode_responses=True)
        self._pub = Redis.from_url(self._url, decode_responses=True)
        self._listener_task = asyncio.create_task(self._listen_loop())
        self._started = True
        await self._resubscribe_all()
        _log.info("redis_bus_started")

    async def close(self) -> None:
        self._started = False
        if self._listener_task:
            self._listener_task.cancel()
        try:
            if self._redis:
                await self._redis.close()
        finally:
            if self._pub:
                await self._pub.close()
        _log.info("redis_bus_closed")

    # ------------------ Внутреннее ------------------

    async def _resubscribe_all(self) -> None:
        """
        Подписываемся на все каналы evt:* согласно сохранённым топикам.
        """
        if not self._redis:
            return
        topics = list(self._subs.keys())
        if not topics:
            return
        channels = [f"evt:{t}" for t in topics] + ["evt:__dlq__"]
        try:
            pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            await pubsub.subscribe(*channels)
            self._active_pubsub = pubsub
            _log.info("redis_bus_resubscribed", extra={"topics": topics})
        except Exception:
            _log.error("redis_bus_resubscribe_failed", extra={"topics": topics}, exc_info=True)

    async def _emit_dlq(self, evt: Dict[str, Any], *, error: str, failed_handler: str) -> None:
        # Локальные DLQ-хендлеры
        for d in self._dlq:
            try:
                await d({"topic": "__dlq__", "payload": {**evt.get("payload", {}), "original_topic": evt.get("topic"), "error": error, "failed_handler": failed_handler}})
            except Exception:
                _log.debug("redis_bus_local_dlq_handler_failed", extra={"topic": evt.get("topic")}, exc_info=True)
        # И в общий канал
        try:
            if self._pub:
                await self._pub.publish("evt:__dlq__", json.dumps({"topic": "__dlq__", "payload": {**evt.get("payload", {}), "original_topic": evt.get("topic"), "error": error, "failed_handler": failed_handler}}))
                inc("redis_bus_dlq_published_total")
        except Exception:
            _log.error("redis_bus_publish_dlq_failed", exc_info=True)

    async def _listen_loop(self) -> None:
        """
        Основной цикл приёма сообщений.
        При разрыве соединения пытается переподключиться и пере-подписаться.
        """
        backoff = 0.5
        while True:
            try:
                if not self._redis:
                    self._redis = Redis.from_url(self._url, decode_responses=True)
                pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
                topics = [f"evt:{t}" for t in self._subs.keys()] + ["evt:__dlq__"]
                if topics:
                    await pubsub.subscribe(*topics)
                self._active_pubsub = pubsub
                _log.info("redis_bus_listen_started", extra={"topics": topics or ["<none>"]})
                observe("redis_bus.listen.backoff_ms", backoff * 1000.0, {"phase": "started"})
                backoff = 0.5  # <- сбросим бэкофф после успешного старта

                async for msg in pubsub.listen():
                    if msg is None:
                        await asyncio.sleep(0.01)
                        continue
                    if msg["type"] != "message":
                        continue
                    t0 = asyncio.get_event_loop().time()
                    try:
                        data = json.loads(msg["data"])
                    except Exception:
                        # невалидное сообщение
                        inc("redis_bus_malformed_total")
                        continue
                    topic = data.get("topic")
                    if not topic:
                        continue
                    if topic == "__dlq__":
                        for d in self._dlq:
                            try:
                                await d(data)
                            except Exception:
                                _log.debug("redis_bus_dlq_handler_failed", exc_info=True)
                        continue
                    handlers = list(self._subs.get(topic, []))
                    delivered = 0
                    for h in handlers:
                        try:
                            await h(data)
                            delivered += 1
                        except Exception as exc:
                            await self._emit_dlq(data, error=str(exc), failed_handler=getattr(h, "__name__", "handler"))
                    inc("redis_bus_delivered_total", topic=topic, delivered=str(delivered))
                    observe("redis_bus.consume.ms", (asyncio.get_event_loop().time() - t0) * 1000.0, {"topic": topic})
            except asyncio.CancelledError:
                break
            except Exception:
                _log.error("redis_bus_listen_error", extra={"next_backoff": backoff}, exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10.0)
                continue
