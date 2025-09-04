from __future__ import annotations

import asyncio
import random
from collections import defaultdict, deque
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
    Унифицированное событие: переносимый формат.
    topic   — строковый канал (например, 'orders.executed')
    payload — произвольный JSON-совместимый словарь
    key     — опциональный ключ для идемпотентности/партиционирования
    ts_ms   — отметка времени отправки события
    """

    topic: str
    payload: dict[str, Any]
    key: str | None = None
    ts_ms: int = 0


class AsyncEventBus:
    """
    Лёгкая асинхронная шина событий без внешних брокеров.

    API:
      - subscribe(topic, handler) / on(topic, handler) — точные подписки
      - subscribe_wildcard("orders.*", handler) / on_wildcard(...) — префиксные подписки
      - subscribe_dlq(handler) — обработчик недоставленных событий
      - publish(topic, payload, key=None) — публикация с ретраями и бэкоффом

    Гарантии: at-most-once (in-process). При включённой дедупликации — best-effort идемпотентность по key.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        backoff_base_ms: int = 250,
        backoff_factor: float = 2.0,
        topic_concurrency: int = 32,
        enable_dedupe: bool = False,
        dedupe_size: int = 2048,
    ) -> None:
        self.max_attempts = int(max_attempts)
        self.backoff_base_ms = int(backoff_base_ms)
        self.backoff_factor = float(backoff_factor)
        self._subs: defaultdict[str, list[Handler]] = defaultdict(list)
        self._wildcard: list[tuple[str, Handler]] = []  # ('orders.' префикс, handler)
        self._dlq: list[Handler] = []
        self._sem = asyncio.Semaphore(max(1, int(topic_concurrency)))
        self._started = False

        # optional idempotency (simple LRU by key)
        self._dedupe_enabled = bool(enable_dedupe)
        self._dedupe_max = max(1, int(dedupe_size))
        self._dedupe_q: deque[str] = deque(maxlen=self._dedupe_max)
        self._dedupe_set: set[str] = set()

    # -------------------------
    # Подписки
    # -------------------------
    def subscribe(self, topic: str, handler: Handler) -> None:
        """Подписка на конкретный topic (точное совпадение)."""
        self._subs[topic].append(handler)
        _log.info(
            "bus_subscribed", extra={"topic": topic, "handler": getattr(handler, "__name__", "handler")}
        )

    # Алиас для совместимости
    def on(self, topic: str, handler: Handler) -> None:
        self.subscribe(topic, handler)

    def subscribe_wildcard(self, pattern: str, handler: Handler) -> None:
        """
        Префиксная подписка: 'orders.*' → все топики, начинающиеся с 'orders.'.
        Простой и быстрый матч без регулярок.
        """
        pat = pattern.rstrip("*")
        self._wildcard.append((pat, handler))
        _log.info(
            "bus_subscribed_wildcard",
            extra={"pattern": pattern, "handler": getattr(handler, "__name__", "handler")},
        )

    # Алиас
    def on_wildcard(self, pattern: str, handler: Handler) -> None:
        self.subscribe_wildcard(pattern, handler)

    def subscribe_dlq(self, handler: Handler) -> None:
        """Подписка на DLQ — получает события, не доставленные обработчикам после ретраев."""
        self._dlq.append(handler)
        _log.info("bus_subscribed_dlq", extra={"handler": getattr(handler, "__name__", "handler")})

    # -------------------------
    # Жизненный цикл
    # -------------------------
    async def start(self) -> None:
        self._started = True
        _log.info("bus_started")

    async def close(self) -> None:
        self._started = False
        _log.info("bus_closed")

    # -------------------------
    # Публикация
    # -------------------------
    async def publish(self, topic: str, payload: dict[str, Any], *, key: str | None = None) -> dict[str, Any]:
        """
        Публикация события локальным подписчикам.
        Если обработчик падает — N ретраев с экспоненциальным бэкоффом и джиттером,
        после чего событие отправляется в DLQ.
        """
        evt = Event(topic=topic, payload=payload, key=key, ts_ms=now_ms())

        # Дедупликация по ключу (опционально)
        if self._dedupe_enabled and evt.key:
            if evt.key in self._dedupe_set:
                inc("bus_publish_deduped_total", topic=topic)
                _log.debug("bus_publish_deduped", extra={"topic": topic, "key": evt.key})
                return {"ok": True, "delivered": 0, "topic": topic, "deduped": True}
            self._dedupe_q.append(evt.key)
            self._dedupe_set.add(evt.key)
            # выталкиваем вышедшие за LRU
            while len(self._dedupe_set) > self._dedupe_max:
                old = self._dedupe_q.popleft()
                self._dedupe_set.discard(old)

        handlers = list(self._subs.get(topic, []))
        if self._wildcard:
            prefix_matches = [h for (pref, h) in self._wildcard if topic.startswith(pref)]
            handlers.extend(prefix_matches)

        if not handlers:
            inc("bus_publish_no_subscribers_total", topic=topic)
            _log.info("bus_published_no_subscribers", extra={"topic": topic})
            return {"ok": True, "delivered": 0, "topic": topic}

        # Доставляем обработчикам с ограничением параллелизма
        delivered = 0

        async def _run(h: Handler) -> bool:
            return await self._deliver_with_retry(h, evt)

        # запускаем все хендлеры параллельно, но limitted семафором на каждую задачу
        async def _guarded(h: Handler) -> bool:
            async with self._sem:
                return await _run(h)

        results = await asyncio.gather(*[_guarded(h) for h in handlers], return_exceptions=True)
        for res, h in zip(results, handlers):
            if isinstance(res, Exception):
                # сюда попадём редко (неожиданная ошибка вне ретраев)
                _log.error(
                    "bus_handler_crashed",
                    extra={"topic": topic, "handler": getattr(h, "__name__", "handler")},
                    exc_info=True,
                )
                await self._emit_to_dlq(evt, failed_handler=getattr(h, "__name__", "handler"))
                inc("bus_handler_failed_total", topic=topic, handler=getattr(h, "__name__", "handler"))
            elif res:
                delivered += 1

        inc("bus_publish_ok_total", topic=topic, delivered=delivered)
        _log.info("bus_published", extra={"topic": topic, "delivered": delivered, "key": key})
        return {"ok": True, "delivered": delivered, "topic": topic}

    # -------------------------
    # Внутренние утилиты
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

    async def _deliver_with_retry(self, handler: Handler, evt: Event) -> bool:
        attempt = 1
        delay_ms = self.backoff_base_ms
        name = getattr(handler, "__name__", "handler")
        topic = evt.topic

        while True:
            try:
                await handler(evt)
                inc("bus_handler_ok_total", topic=topic, handler=name)
                return True
            except Exception:
                if attempt >= self.max_attempts:
                    _log.error(
                        "bus_handler_failed",
                        extra={"topic": topic, "handler": name, "attempt": attempt},
                        exc_info=True,
                    )
                    await self._emit_to_dlq(evt, failed_handler=name)
                    return False

                # джиттерный бэкофф
                jitter = delay_ms * 0.25
                sleep_s = max(0.001, (delay_ms + random.uniform(-jitter, jitter)) / 1000.0)
                _log.debug(
                    "bus_handler_retry",
                    extra={
                        "topic": topic,
                        "handler": name,
                        "attempt": attempt,
                        "next_delay_ms": int(sleep_s * 1000),
                    },
                )
                await asyncio.sleep(sleep_s)
                attempt += 1
                delay_ms = int(delay_ms * self.backoff_factor)

    # -------------------------
    # Утилиты для простого подключения
    # -------------------------
    def attach_logger_dlq(self) -> None:
        """Включить дефолтный DLQ-логгер, если своих подписчиков нет."""

        async def _log_dlq(e: Event) -> None:
            _log.error("DLQ", extra={"topic": e.payload.get("original_topic"), "payload": e.payload})

        if not self._dlq:
            self.subscribe_dlq(_log_dlq)
