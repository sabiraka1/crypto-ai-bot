# src/crypto_ai_bot/core/events/bus.py
"""
Асинхронная шина событий для обмена сообщениями между компонентами системы.
Поддерживает публикацию/подписку с очередью и обработкой ошибок.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict, NotRequired

logger = logging.getLogger("events.bus")

# Тип обработчика событий
Handler = Callable[[str, Dict[str, Any]], Awaitable[None]]


class BusEvent(TypedDict, total=False):
    """Базовое событие шины с общими полями."""
    type: str
    ts_ms: int
    symbol: str
    timeframe: str
    payload: NotRequired[Dict[str, Any]]
    error: NotRequired[str]


class DecisionEvaluatedEvent(BusEvent, total=False):
    """Событие о принятом торговом решении."""
    type: str  # "DecisionEvaluated"
    decision: Dict[str, Any]


class OrderExecutedEvent(BusEvent, total=False):
    """Событие об исполненном ордере."""
    type: str  # "OrderExecuted"
    order_id: str
    side: str
    qty: str
    price: float


class AsyncEventBus:
    """
    Единый асинхронный шиной.
    - publish() — неблокирующая публикация (кладём в очередь)
    - worker-поток доставляет сообщения подписчикам (параллельно, но с ограничением concurrency)
    - DLQ на ошибки, health()
    """
    def __init__(self, *, max_queue: int = 1000, concurrency: int = 8) -> None:
        """
        Инициализация шины событий.
        
        Args:
            max_queue: Максимальный размер очереди событий
            concurrency: Количество worker-потоков для обработки
        """
        self._q: asyncio.Queue[tuple[str, Dict[str, Any]]] = asyncio.Queue(max_queue)
        self._handlers: Dict[str, List[Handler]] = {}
        self._dlq: List[Dict[str, Any]] = []  # Dead Letter Queue для ошибок
        self._running = False
        self._workers: List[asyncio.Task] = []
        self._concurrency = max(1, int(concurrency))

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Подписаться на события определенного типа."""
        self._handlers.setdefault(topic, []).append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """Опубликовать событие в шину (неблокирующе)."""
        if not self._running:
            logger.warning("event bus not running; dropping event topic=%s", topic)
            return
        await self._q.put((topic, payload))

    def health(self) -> Dict[str, Any]:
        """Получить статус здоровья шины событий."""
        return {
            "running": self._running,
            "queue_size": self._q.qsize() if self._running else None,
            "queue_cap": self._q.maxsize if self._running else None,
            "dlq_size": len(self._dlq),
        }

    async def _worker(self) -> None:
        """Worker-поток для обработки событий из очереди."""
        while self._running:
            try:
                topic, payload = await self._q.get()
                handlers = list(self._handlers.get(topic, []))
                if not handlers:
                    self._q.task_done()
                    continue

                # доставляем параллельно, но ждём все
                async def _deliver(h: Handler) -> None:
                    """Доставка события одному обработчику с обработкой ошибок."""
                    try:
                        await h(topic, payload)
                    except Exception as e:
                        logger.exception("event handler failed: %s", e)
                        self._dlq.append({"topic": topic, "payload": payload, "error": repr(e)})

                await asyncio.gather(*[_deliver(h) for h in handlers], return_exceptions=False)
                self._q.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("event bus worker failed: %s", e)

    async def start(self) -> None:
        """Запустить шину событий."""
        if self._running:
            return
        self._running = True
        self._workers = [asyncio.create_task(self._worker(), name=f"bus-worker-{i}") for i in range(self._concurrency)]

    async def stop(self) -> None:
        """Остановить шину событий."""
        if not self._running:
            return
        self._running = False
        # Отменяем все worker-задачи
        for t in self._workers:
            t.cancel()
        # Ждем завершения всех worker-ов
        for t in self._workers:
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("bus worker termination error: %s", e)
        self._workers.clear()