from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import suppress
import json
from typing import Any, Dict, List, Optional

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

# Тип обработчика: получает payload (dict)
Handler = Callable[[dict[str, Any]], Awaitable[None]]

_log = get_logger("events.redis_bus")


class RedisEventBus:
    """
    Простая асинхронная шина событий поверх Redis Pub/Sub.

    Особенности:
      - start()/stop() идемпотентные;
      - publish можно вызывать до start() — клиент создастся лениво;
      - on/on_wildcard регистрируют корутины-обработчики (topic → dict payload);
      - слушающий цикл: читает PubSub и диспатчит в соответствующие хэндлеры;
      - JSON-пакет: {"key": <опц. ключ>, "payload": <данные>}.
    """

    def __init__(
        self,
        url: str,
        *,
        ping_interval: float = 15.0,
        hard_timeout: float = 10.0,
        channel_prefix: str = "",
    ) -> None:
        self._url = url
        self._ping_interval = float(ping_interval)
        self._hard_timeout = float(hard_timeout)
        self._prefix = channel_prefix.rstrip(":")

        self._r: Optional[Redis] = None
        self._ps: Optional[PubSub] = None

        self._started = False
        self._listen_task: Optional[asyncio.Task[None]] = None

        # Хендлеры топиков и паттернов
        self._handlers: Dict[str, List[Handler]] = defaultdict(list)
        self._p_handlers: Dict[str, List[Handler]] = defaultdict(list)

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        if self._started:
            return
        self._r = Redis.from_url(self._url, decode_responses=True)
        self._ps = self._r.pubsub(ignore_subscribe_messages=True)
        self._started = True

        # Подписываем уже зарегистрированные обработчики
        if self._handlers and self._ps:
            topics = list(self._handlers.keys())
            with suppress(Exception):
                await self._ps.subscribe(*topics)
                for t in topics:
                    inc("bus_subscribe_total", topic=t)

        if self._p_handlers and self._ps:
            patterns = list(self._p_handlers.keys())
            with suppress(Exception):
                await self._ps.psubscribe(*patterns)
                for p in patterns:
                    inc("bus_psubscribe_total", pattern=p)

        # Запускаем слушающий цикл
        self._listen_task = asyncio.create_task(self._listen_loop(), name="redis-bus-listen")
        _log.info("redis_bus_started", extra={"url": self._url})

    async def stop(self) -> None:
        if not self._started:
            return

        self._started = False

        # Останавливаем слушатель
        t = self._listen_task
        self._listen_task = None
        if t:
            t.cancel()
            with suppress(Exception):
                await t

        # Отписка и закрытие PubSub
        if self._ps is not None:
            with suppress(Exception):
                await self._ps.unsubscribe()
            with suppress(Exception):
                await self._ps.punsubscribe()
            with suppress(Exception):
                await self._ps.close()
            self._ps = None

        # Закрываем Redis
        if self._r is not None:
            with suppress(Exception):
                await self._r.close()
            self._r = None

        _log.info("redis_bus_stopped")

    # Совместимость с адаптерами
    async def close(self) -> None:
        await self.stop()

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _full_topic(self, topic: str) -> str:
        if not self._prefix:
            return topic
        return f"{self._prefix}:{topic}"

    # ------------------------------------------------------------------ #
    # publish / subscribe
    # ------------------------------------------------------------------ #

    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None:
        """
        Публикует событие в канал Redis.

        Args:
            topic: имя канала
            payload: данные события (dict)
            key: опциональный ключ (для идемпотентности/группировки)
        """
        if self._r is None:
            # ленивое подключение, если publish вызвали до start()
            self._r = Redis.from_url(self._url, decode_responses=True)

        topic = self._full_topic(topic)

        msg = {"key": key, "payload": payload}
        data = json.dumps(msg, ensure_ascii=False)

        try:
            async with asyncio.timeout(self._hard_timeout):
                await self._r.publish(topic, data)  # type: ignore[func-returns-value]
            inc("bus_publish_total", topic=topic)
        except Exception:
            _log.error("redis_publish_failed", extra={"topic": topic}, exc_info=True)

    def on(self, topic: str, handler: Handler) -> None:
        """Подписка на конкретный топик (обработчик — корутина)."""
        self._handlers[self._full_topic(topic)].append(handler)
        # Если уже запущены — фоновой таской подписываемся
        if self._started and self._ps:
            asyncio.create_task(self._safe_subscribe(self._full_topic(topic)))

    def on_wildcard(self, pattern: str, handler: Handler) -> None:
        """Подписка по паттерну (psubscribe, например 'orders.*')."""
        # Префикс добавляем как namespace
        patt = self._full_topic(pattern)
        self._p_handlers[patt].append(handler)
        if self._started and self._ps:
            asyncio.create_task(self._safe_psubscribe(patt))

    async def _safe_subscribe(self, topic: str) -> None:
        """Фоновая подписка с безопасным логированием ошибок."""
        try:
            if self._ps:
                await self._ps.subscribe(topic)
                inc("bus_subscribe_total", topic=topic)
        except Exception:
            _log.error("redis_subscribe_failed", extra={"topic": topic}, exc_info=True)

    async def _safe_psubscribe(self, pattern: str) -> None:
        """Фоновая psubscribe с безопасным логированием ошибок."""
        try:
            if self._ps:
                await self._ps.psubscribe(pattern)
                inc("bus_psubscribe_total", pattern=pattern)
        except Exception:
            _log.error("redis_psubscribe_failed", extra={"pattern": pattern}, exc_info=True)

    # ------------------------------------------------------------------ #
    # listen loop
    # ------------------------------------------------------------------ #

    async def _listen_loop(self) -> None:
        """
        Основной цикл: поддерживаем соединение пингами и читаем сообщения PubSub.
        """
        assert self._ps is not None
        last_ping = 0.0

        try:
            while self._started:
                # поддерживающий ping
                if self._r and (self._ping_interval > 0):
                    now = asyncio.get_running_loop().time()
                    if now - last_ping > self._ping_interval:
                        try:
                            async with asyncio.timeout(self._hard_timeout):
                                await self._r.ping()
                        except Exception:
                            _log.warning("redis_ping_failed", exc_info=True)
                        last_ping = now

                # читаем следующее сообщение
                try:
                    msg = await self._ps.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,  # сек.
                    )
                except Exception:
                    _log.error("redis_get_message_failed", exc_info=True)
                    msg = None

                if not msg:
                    # ничего не пришло — новая итерация
                    continue

                # typ = msg.get("type")  # можно раскомментировать для отладки
                topic = str(msg.get("channel", "") or "")
                pattern = str(msg.get("pattern", "") or "")
                raw = msg.get("data", "")

                payload: dict[str, Any]
                try:
                    decoded = json.loads(raw)
                    payload = decoded.get("payload", {}) if isinstance(decoded, dict) else {}
                except Exception:
                    payload = {}
                    _log.error("redis_message_decode_failed", extra={"topic": topic}, exc_info=True)

                # метрики получения
                if topic:
                    inc("bus_received_total", topic=topic)
                if pattern:
                    inc("bus_received_total", pattern=pattern)

                # Диспатчим: точное совпадение канала
                if topic:
                    for handler in list(self._handlers.get(topic, [])):
                        try:
                            await handler(payload)
                        except Exception:
                            _log.error("handler_failed", extra={"topic": topic}, exc_info=True)
                            inc("bus_handler_errors_total", topic=topic)

                # И по паттерну (если есть)
                if pattern:
                    for handler in list(self._p_handlers.get(pattern, [])):
                        try:
                            await handler(payload)
                        except Exception:
                            _log.error("handler_failed", extra={"pattern": pattern}, exc_info=True)
                            inc("bus_handler_errors_total", pattern=pattern)

        except asyncio.CancelledError:
            # штатное завершение
            pass
        except Exception:
            _log.error("redis_listen_loop_crashed", exc_info=True)
