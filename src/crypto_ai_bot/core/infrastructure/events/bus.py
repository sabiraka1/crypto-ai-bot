from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, DefaultDict, Dict, List, Optional
from collections import defaultdict

# Мягкая интеграция с метриками (без обязательной зависимости)
try:
    from crypto_ai_bot.utils.metrics import inc  # type: ignore
except Exception:  # pragma: no cover
    def inc(_name: str, **_labels: Any) -> None:  # no-op
        pass

try:
    from crypto_ai_bot.utils.time import now_ms  # type: ignore
except Exception:  # pragma: no cover
    import time
    def now_ms() -> int:
        return int(time.time() * 1000)

try:
    from crypto_ai_bot.utils.logging import get_logger  # type: ignore
except Exception:  # pragma: no cover
    import logging
    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

_log = get_logger("events.bus")


Handler = Callable[["Event"], Awaitable[None]]


@dataclass(frozen=True)
class Event:
    """
    Событие шины: минимальный переносимый формат.
    topic   — строковый канал (например, 'orders.executed')
    payload — произвольный JSON-совместимый словарь
    key     — опциональный ключ партиционирования/идемпотентности
    ts_ms   — отметка времени отправки события
    """
    topic: str
    payload: Dict[str, Any]
    key: Optional[str] = None
    ts_ms: int = 0


class AsyncEventBus:
    """
    Лёгкая асинхронная шина событий без внешних брокеров:
      - subscribe(topic, handler) / subscribe_dlq(handler)
      - publish(topic, payload, key=None) с ретраями и бэкоффом
      - обработка ошибок через DLQ-подписчиков
    Гарантии доставки: at-most-once (in-process).
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
        self._subs: DefaultDict[str, List[Handler]] = defaultdict(list)
        self._dlq: List[Handler] = []

    # -------------------------
    # Подписки
    # -------------------------
    def subscribe(self, topic: str, handler: Handler) -> None:
        """Подписка на конкретный topic (точное совпадение)."""
        self._subs[topic].append(handler)
        _log.info("bus_subscribed", extra={"topic": topic, "handler": getattr(handler, "__name__", "handler")})

    def subscribe_dlq(self, handler: Handler) -> None:
        """Подписка на DLQ — получает события, не доставленные обработчикам после ретраев."""
        self._dlq.append(handler)
        _log.info("bus_subscribed_dlq", extra={"handler": getattr(handler, "__name__", "handler")})

    # -------------------------
    # Публикация
    # -------------------------
    async def publish(self, topic: str, payload: Dict[str, Any], *, key: Optional[str] = None) -> Dict[str, Any]:
        """
        Публикация события с синхронной доставкой локальным подписчикам.
        Если обработчик падает — N ретраев с экспоненциальным бэкоффом,
        затем событие отправляется в DLQ.
        """
        evt = Event(topic=topic, payload=payload, key=key, ts_ms=now_ms())
        handlers = list(self._subs.get(topic, []))
        if not handlers:
            # Нет подписчиков — это не ошибка
            inc("bus_publish_no_subscribers_total", topic=topic)
            return {"ok": True, "delivered": 0, "topic": topic}

        delivered = 0
        for h in handlers:
            attempt = 1
            delay_ms = self.backoff_base_ms
            while True:
                try:
                    await h(evt)
                    delivered += 1
                    inc("bus_handler_ok_total", topic=topic, handler=getattr(h, "__name__", "handler"))
                    break
                except Exception as exc:  # pragma: no cover (путь деградации)
                    if attempt >= self.max_attempts:
                        _log.error(
                            "bus_handler_failed",
                            extra={"topic": topic, "handler": getattr(h, "__name__", "handler"), "error": str(exc)},
                        )
                        inc("bus_handler_failed_total", topic=topic, handler=getattr(h, "__name__", "handler"))
                        await self._emit_to_dlq(evt, error=str(exc), failed_handler=getattr(h, "__name__", "handler"))
                        break
                    # экспоненциальный бэкофф
                    await asyncio.sleep(max(0.001, delay_ms / 1000))
                    attempt += 1
                    delay_ms = int(delay_ms * self.backoff_factor)

        inc("bus_publish_ok_total", topic=topic, delivered=delivered)
        _log.info("bus_published", extra={"topic": topic, "delivered": delivered, "key": key})
        return {"ok": True, "delivered": delivered, "topic": topic}

    # -------------------------
    # Внутреннее: отправка в DLQ
    # -------------------------
    async def _emit_to_dlq(self, evt: Event, *, error: str, failed_handler: str) -> None:
        if not self._dlq:
            return
        dlq_evt = Event(
            topic="__dlq__",
            payload={"original_topic": evt.topic, "error": error, "failed_handler": failed_handler, **evt.payload},
            key=evt.key,
            ts_ms=now_ms(),
        )
        for d in self._dlq:
            try:
                await d(dlq_evt)
                inc("bus_dlq_delivered_total", original_topic=evt.topic)
            except Exception:
                # DLQ — best-effort; не эскалируем
                inc("bus_dlq_handler_failed_total", original_topic=evt.topic)

    # -------------------------
    # Утилиты для простого подключения
    # -------------------------
    def attach_logger_dlq(self) -> None:
        """Включить дефолтный DLQ-логгер, если своих подписчиков нет."""
        async def _log_dlq(e: Event) -> None:
            _log.error("DLQ", extra={"topic": e.payload.get("original_topic"), "payload": e.payload})
        if not self._dlq:
            self.subscribe_dlq(_log_dlq)
