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
    Асинхронная шина событий на Redis Pub/Sub.
      - publish(topic: str, payload: dict, key: str|None = None)
      - on(topic, handler) — точные подписки
      - on_wildcard("orders.*", handler) — паттерн-подписки (psubscribe)
      - start()/close() — управление жизненным циклом
    Гарантии доставки Pub/Sub: at-most-once (без очередей).
    """

    def __init__(
        self,
        url: str,
        *,
        ping_interval_sec: float = 30.0,
        hard_timeout_sec: float = 10.0,
    ) -> None:
        if not url:
            raise ValueError("RedisEventBus requires non-empty redis url (e.g. redis://...)")
        self._url = url
        self._r: Redis | None = None
        self._ps: PubSub | None = None
        self._task: asyncio.Task[None] | None = None
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._p_handlers: dict[str, list[Handler]] = defaultdict(list)  # pattern -> handlers
        self._topics: set[str] = set()
        self._patterns: set[str] = set()
        self._ping_interval = float(ping_interval_sec)
        self._hard_timeout = float(hard_timeout_sec)
        self._started = False

    # -------- lifecycle --------
    async def start(self) -> None:
        """Запустить шину (ленивое подключение и подписка)."""
        if self._started:
            return
        self._r = Redis.from_url(self._url, encoding="utf-8", decode_responses=True)
        self._ps = self._r.pubsub()
        if self._topics:
            await self._ps.subscribe(*self._topics)
        if self._patterns:
            await self._ps.psubscribe(*self._patterns)
        self._started = True
        self._task = asyncio.create_task(self._listen_loop())
        _log.info("redis_bus_started", extra={"url": self._url})

    async def close(self) -> None:
        """Остановить шину и закрыть ресурсы."""
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

    # совместимость/алиас
    async def stop(self) -> None:
        await self.close()

    # -------- api --------
    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None:
        """Публикация события в топик (с hard-timeout и безопасной ленивой инициализацией)."""
        if not isinstance(payload, dict):
            raise TypeError("payload must be dict")

        if not self._r:
            # разрешаем publish до start(): лениво инициализируем клиент
            self._r = Redis.from_url(self._url, encoding="utf-8", decode_responses=True)

        msg = {"key": key, "payload": payload}
        data = json.dumps(msg, ensure_ascii=False)

        try:
            async with asyncio.timeout(self._hard_timeout):
                await self._r.publish(topic, data)
            inc("bus_publish_total", topic=topic)
        except Exception:
            _log.error("redis_publish_failed", extra={"topic": topic}, exc_info=True)

    def on(self, topic: str, handler: Handler) -> None:
        """Подписка на конкретный топик (обработчик — корутина)."""
        self._handlers[topic].append(handler)
        self._topics.add(topic)
        # если уже стартовали — подписываемся немедленно
        if self._started and self._ps:
            asyncio.create_task(self._ps.subscribe(topic))

    # alias
    def on_wildcard(self, pattern: str, handler: Handler) -> None:
        """
        Паттерн-подписка: 'orders.*' → psubscribe('orders.*').
        Обработчик принимает payload (dict).
        """
        self._p_handlers[pattern].append(handler)
        self._patterns.add(pattern)
        if self._started and self._ps:
            asyncio.create_task(self._ps.psubscribe(pattern))

    # -------- internals --------
    async def _listen_loop(self) -> None:
        """Основной цикл чтения сообщений Pub/Sub."""
        assert self._ps is not None
        last_ping = 0.0

        try:
            while self._started:
                # ping для поддержания соединения
                if self._r and (self._ping_interval > 0):
                    now = asyncio.get_event_loop().time()
                    if now - last_ping > self._ping_interval:
                        try:
                            async with asyncio.timeout(self._hard_timeout):
                                await self._r.ping()
                        except Exception:
                            _log.warning("redis_ping_failed", exc_info=True)
                        last_ping = now

                # читаем сообщение
                msg = await self._ps.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not msg:
                    await asyncio.sleep(0.05)
                    continue

                typ = msg.get("type")
                topic = str(msg.get("channel", "") or "")
                pattern = str(msg.get("pattern", "") or "")
                raw = msg.get("data", "")

                try:
                    obj = json.loads(raw) if isinstance(raw, str) and raw else {}
                except Exception:
                    obj = {}

                payload = obj.get("payload", {}) if isinstance(obj, dict) else {}

                # точечные обработчики
                for handler in list(self._handlers.get(topic, [])):
                    try:
                        await handler(payload)
                    except Exception:
                        _log.error("handler_failed", extra={"topic": topic}, exc_info=True)
                        inc("bus_handler_errors_total", topic=topic)

                # паттерн-обработчики
                if pattern:
                    for handler in list(self._p_handlers.get(pattern, [])):
                        try:
                            await handler(payload)
                        except Exception:
                            _log.error("handler_failed", extra={"pattern": pattern}, exc_info=True)
                            inc("bus_handler_errors_total", pattern=pattern)

        except asyncio.CancelledError:
            pass
        except Exception:
            _log.error("redis_listen_loop_crashed", exc_info=True)
