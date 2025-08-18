# src/crypto_ai_bot/core/events/bus.py
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from crypto_ai_bot.utils.metrics import inc, gauge
from crypto_ai_bot.utils.logging import REQUEST_ID, get_logger

log = get_logger("eventbus")

EventHandler = Callable[[str, Dict[str, Any]], Awaitable[None]]  # async (topic, payload) -> None

@dataclass
class _Sub:
    topic: str
    handler: EventHandler
    priority: int

@dataclass
class _Evt:
    ts: int
    topic: str
    payload: Dict[str, Any]
    priority: int
    correlation_id: Optional[str]

class AsyncEventBus:
    """
    Асинхронная шина событий с:
      - bounded queue (backpressure policy)
      - приоритетами обработчиков
      - DLQ с ограничением размера
      - health() и метрики
    Совместимость:
      publish(topic, payload, priority=0) ИЛИ publish({"topic":..., "payload":...})
    """

    def __init__(
        self,
        *,
        max_queue: int = 2000,
        dlq_limit: int = 500,
        workers: int = 4,
        backpressure: str = "drop_new",   # 'drop_new' | 'drop_oldest' | 'block'
        enqueue_timeout_sec: float = 0.25,
    ) -> None:
        self._subs: List[_Sub] = []
        self._q: asyncio.Queue[_Evt] = asyncio.Queue(maxsize=max_queue)
        self._dlq: List[_Evt] = []
        self._dlq_limit = int(max(0, dlq_limit))
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._workers_n = max(1, int(workers))
        self._backpressure = backpressure
        self._enq_timeout = float(enqueue_timeout_sec)

        # статистика
        self._processed = 0
        self._dropped = 0
        self._failed = 0

    # ---------- API ----------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for i in range(self._workers_n):
            t = asyncio.create_task(self._worker(i))
            self._workers.append(t)
        log.info("eventbus_started", extra={"extra": {"workers": self._workers_n}})

    def stop(self) -> None:
        self._running = False
        for t in self._workers:
            t.cancel()
        self._workers.clear()
        log.info("eventbus_stopped", extra={"extra": {}})

    def subscribe(self, topic: str, handler: EventHandler, *, priority: int = 0) -> None:
        self._subs.append(_Sub(topic=topic, handler=handler, priority=int(priority)))
        # сортируем по убыванию приоритета
        self._subs.sort(key=lambda s: s.priority, reverse=True)

    async def publish(
        self,
        topic_or_event: Union[str, Dict[str, Any]],
        payload: Optional[Dict[str, Any]] = None,
        *,
        priority: int = 0,
    ) -> None:
        """
        Совместимый publish:
          - publish("topic", {...}, priority=1)
          - publish({"topic":"...", "payload":{...}, "priority":1})
        """
        if isinstance(topic_or_event, dict):
            topic = str(topic_or_event.get("topic") or "")
            payload = dict(topic_or_event.get("payload") or {})
            priority = int(topic_or_event.get("priority") or 0)
        else:
            topic = str(topic_or_event or "")
            payload = dict(payload or {})

        evt = _Evt(
            ts=int(time.time() * 1000),
            topic=topic,
            payload=payload,
            priority=priority,
            correlation_id=REQUEST_ID.get(),
        )
        await self._enqueue(evt)

    # старое имя, если где-то использовалось
    async def emit(self, *args, **kwargs) -> None:
        await self.publish(*args, **kwargs)

    def health(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "queue_size": self._q.qsize(),
            "queue_cap": self._q.maxsize,
            "dlq_size": len(self._dlq),
            "processed": self._processed,
            "failed": self._failed,
            "dropped": self._dropped,
        }

    # ---------- внутренняя логика ----------

    async def _enqueue(self, evt: _Evt) -> None:
        # метрики и backpressure
        # пробуем немедленно
        try:
            self._q.put_nowait(evt)
            gauge("bus_queue_size", self._q.qsize(), {})
            return
        except asyncio.QueueFull:
            pass

        policy = self._backpressure
        if policy == "drop_new":
            self._dropped += 1
            inc("bus_drop", {"policy": "drop_new"})
            return
        elif policy == "drop_oldest":
            try:
                _ = self._q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._q.put_nowait(evt)
                gauge("bus_queue_size", self._q.qsize(), {})
                inc("bus_drop", {"policy": "drop_oldest"})
                self._dropped += 1
                return
            except asyncio.QueueFull:
                # если прямо сейчас всё равно full — как drop_new
                self._dropped += 1
                inc("bus_drop", {"policy": "drop_new"})
                return
        else:  # 'block'
            try:
                await asyncio.wait_for(self._q.put(evt), timeout=self._enq_timeout)
                gauge("bus_queue_size", self._q.qsize(), {})
                return
            except asyncio.TimeoutError:
                self._dropped += 1
                inc("bus_drop", {"policy": "block_timeout"})
                return

    async def _worker(self, wid: int) -> None:
        try:
            while True:
                evt = await self._q.get()
                # находим подписчиков (точное совпадение топика)
                subs = [s for s in self._subs if s.topic == evt.topic]
                if not subs:
                    self._processed += 1
                    inc("bus_processed", {"topic": evt.topic})
                    continue

                # выполняем по приоритету, но отдельно, чтобы handler не блокировали очередь
                for s in subs:
                    try:
                        await s.handler(evt.topic, dict(evt.payload))
                    except Exception as e:
                        self._failed += 1
                        self._to_dlq(evt)
                        log.error("event_handler_error", extra={"extra": {"topic": evt.topic, "err": repr(e)}})
                        inc("bus_failed", {"topic": evt.topic})
                self._processed += 1
                inc("bus_processed", {"topic": evt.topic})
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.error("event_worker_crashed", extra={"extra": {"err": repr(e), "wid": wid}})

    def _to_dlq(self, evt: _Evt) -> None:
        if self._dlq_limit <= 0:
            return
        self._dlq.append(evt)
        if len(self._dlq) > self._dlq_limit:
            # отрезаем старые
            del self._dlq[: len(self._dlq) - self._dlq_limit]
        gauge("bus_dlq_size", len(self._dlq), {})


# глобальный геттер (совместимость со старым кодом)
_bus_singleton: Optional[AsyncEventBus] = None

def get_event_bus() -> AsyncEventBus:
    global _bus_singleton
    if _bus_singleton is None:
        _bus_singleton = AsyncEventBus()
        _bus_singleton.start()
    return _bus_singleton
