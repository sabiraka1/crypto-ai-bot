from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...utils.time import now_ms
from ...utils.metrics import inc, timer
from ...utils.logging import get_logger
from ...utils.exceptions import TransientError, ValidationError, BrokerError

Handler = Callable[["Event"], Awaitable[None]]


@dataclass
class Event:
    """Единый формат события внутри шины."""
    topic: str
    key: str  # ключ упорядочивания (обязателен)
    payload: Dict[str, Any]
    ts_ms: int = field(default_factory=now_ms)
    correlation_id: Optional[str] = None


@dataclass
class DeadLetter:
    """Сообщение, попавшее в DLQ после исчерпания попыток обработчика."""
    event: Event
    handler_name: str
    attempts: int
    error: str
    ts_ms: int = field(default_factory=now_ms)


class AsyncEventBus:
    """Асинхронная шина событий с порядком по ключу и DLQ.

    Особенности:
    * Порядок: для каждой пары (topic, key) отдельная очередь и воркер, который обрабатывает события строго последовательно.
    * Несколько обработчиков на тему: вызываются по очереди.
    * Retry на временных ошибках обработчика.
    * DLQ: после неудачных попыток событие уходит в DLQ.
    * ГРЕЙСФУЛ ШАТДАУН: воркеры корректно заканчиваются при отмене/закрытии event loop (без PytestUnraisableExceptionWarning).
    """

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        backoff_base_ms: int = 250,
        backoff_factor: float = 2.0,
        retry_on: Tuple[type, ...] = (TransientError, TimeoutError, ConnectionError),
    ) -> None:
        self._log = get_logger("events.bus")

        self._handlers: Dict[str, List[Handler]] = {}
        self._queues: Dict[Tuple[str, str], asyncio.Queue[Event]] = {}
        self._workers: Dict[Tuple[str, str], asyncio.Task] = {}
        self._dlq_queue: asyncio.Queue[DeadLetter] = asyncio.Queue()
        self._dlq_handlers: List[Handler] = []

        self._max_attempts = max_attempts
        self._backoff_base_ms = backoff_base_ms
        self._backoff_factor = backoff_factor
        self._retry_on = retry_on

        self._closing = False
        self._started = False
        self._dlq_worker: Optional[asyncio.Task] = None

    # ---------- public API ----------

    def qsize(self) -> int:
        """Общее количество событий во всех per-key очередях."""
        return sum(q.qsize() for q in self._queues.values())

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Подписать обработчик на тему."""
        self._handlers.setdefault(topic, []).append(handler)
        self._log.info("subscribed", extra={"topic": topic, "handler": getattr(handler, "__name__", str(handler))})

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        lst = self._handlers.get(topic)
        if not lst:
            return
        try:
            lst.remove(handler)
            self._log.info("unsubscribed", extra={"topic": topic, "handler": getattr(handler, "__name__", str(handler))})
        except ValueError:
            pass

    def subscribe_dlq(self, handler: Handler) -> None:
        """Подписать обработчик для DLQ."""
        self._dlq_handlers.append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any], *, key: str, correlation_id: Optional[str] = None) -> None:
        """Опубликовать событие. Ключ обязателен для гарантии порядка по ключу."""
        if self._closing:
            raise RuntimeError("EventBus is closing")
        if not topic or not isinstance(topic, str):
            raise ValueError("topic must be non-empty string")
        if not key or not isinstance(key, str):
            raise ValueError("key must be non-empty string")

        self._ensure_started()

        event = Event(topic=topic, key=key, payload=dict(payload or {}), correlation_id=correlation_id)
        inc("events_published", {"topic": topic})
        await self._enqueue(event)

    async def start(self) -> None:
        """Явный запуск шины (опционально)."""
        self._ensure_started()

    async def stop(self) -> None:
        """Синоним close() для API-симметрии."""
        await self.close()

    async def close(self) -> None:
        """Остановить всех воркеров и очистить очереди (без ворнингов при закрытии цикла)."""
        self._closing = True

        # Отменяем per-key воркеры
        for task in list(self._workers.values()):
            if not task.done():
                task.cancel()

        # Отменяем DLQ воркер
        if self._dlq_worker and not self._dlq_worker.done():
            self._dlq_worker.cancel()

        # Ждём завершения всех задач
        all_tasks = list(self._workers.values())
        if self._dlq_worker:
            all_tasks.append(self._dlq_worker)

        if all_tasks:
            try:
                await asyncio.gather(*all_tasks, return_exceptions=True)
            except Exception:
                # не даём упасть при закрытии цикла
                pass

        # Очистка состояния
        self._workers.clear()
        self._queues.clear()
        self._dlq_worker = None
        self._started = False

    # ---------- internals ----------

    def _ensure_started(self) -> None:
        """Ленивый запуск: создаём DLQ-воркер только при наличии активного event loop."""
        if self._started:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # нет активного цикла — запустится при первом async publish/await
            return

        if self._dlq_worker is None:
            self._dlq_worker = loop.create_task(self._run_dlq_worker(), name="eventbus-dlq-worker")
        self._started = True
        self._log.info("event_bus_started")

    async def _enqueue(self, event: Event) -> None:
        """Отправить событие в очередь конкретного ключа (создать воркер при необходимости)."""
        key = (event.topic, event.key)
        if key not in self._queues:
            q: asyncio.Queue[Event] = asyncio.Queue()
            self._queues[key] = q
            self._workers[key] = asyncio.create_task(
                self._run_worker(event.topic, event.key, q),
                name=f"eventbus-worker-{event.topic}-{event.key}",
            )
        await self._queues[key].put(event)

    async def _run_worker(self, topic: str, key: str, queue: asyncio.Queue[Event]) -> None:
        """Per-key воркер: строго последовательная обработка событий для (topic, key)."""
        self._log.info("worker_started", extra={"topic": topic, "key": key})
        try:
            while True:
                # мягкое завершение: если закрываемся и очередь пуста — выходим
                if self._closing and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                except (asyncio.CancelledError, RuntimeError, GeneratorExit):
                    # отмена/закрытие цикла — мягко выходим
                    break

                try:
                    with timer("event_handle_ms", {"topic": topic}, unit="ms"):
                        await self._dispatch_event(event)
                finally:
                    try:
                        queue.task_done()
                    except Exception:
                        pass
        except asyncio.CancelledError:
            # нормальная отмена при закрытии
            pass
        except Exception as exc:
            # safety net — не даём «Task was destroyed…»
            self._log.error("worker_crashed", extra={"topic": topic, "key": key, "error": str(exc)})
        finally:
            self._log.info("worker_stopped", extra={"topic": topic, "key": key})

    async def _dispatch_event(self, event: Event) -> None:
        """Вызов обработчиков темы с retry и DLQ."""
        handlers = list(self._handlers.get(event.topic, []))
        if not handlers:
            inc("events_processed", {"topic": event.topic, "status": "no_handlers"})
            return

        for handler in handlers:
            name = getattr(handler, "__name__", str(handler))
            ok = await self._call_with_retries(handler, event)
            if ok:
                inc("events_processed", {"topic": event.topic, "handler": name, "status": "ok"})
            else:
                await self._to_dlq(event, handler)
                inc("events_processed", {"topic": event.topic, "handler": name, "status": "dlq"})

    async def _call_with_retries(self, handler: Handler, event: Event) -> bool:
        """Retry только на временных ошибках; бизнес-ошибки — без повторов."""
        name = getattr(handler, "__name__", str(handler))
        attempt = 1
        while attempt <= self._max_attempts:
            try:
                await handler(event)
                return True
            except self._retry_on as exc:
                if attempt == self._max_attempts:
                    self._log.error("handler_failed_retriable", extra={
                        "handler": name, "topic": event.topic, "key": event.key,
                        "attempts": attempt, "error": str(exc)
                    })
                    return False
                sleep_ms = int(self._backoff_base_ms * (self._backoff_factor ** (attempt - 1)))
                await asyncio.sleep(sleep_ms / 1000.0)
                attempt += 1
            except (ValidationError, BrokerError) as exc:
                self._log.error("handler_failed_nonretriable", extra={
                    "handler": name, "topic": event.topic, "key": event.key, "error": str(exc)
                })
                return False
            except asyncio.CancelledError:
                # закрытие — считаем как неуспех без DLQ (воркер завершится)
                return False
            except Exception as exc:
                self._log.error("handler_failed_unexpected", extra={
                    "handler": name, "topic": event.topic, "key": event.key, "error": str(exc)
                })
                return False
        return False

    async def _to_dlq(self, event: Event, handler: Handler) -> None:
        """Положить запись в DLQ-очередь."""
        name = getattr(handler, "__name__", str(handler))
        dlq = DeadLetter(event=event, handler_name=name, attempts=self._max_attempts, error="handler failed")
        try:
            await self._dlq_queue.put(dlq)
            inc("events_dlq", {"topic": event.topic, "handler": name})
        except asyncio.CancelledError:
            # закрытие — пропускаем, чтобы не держать цикл
            pass

    async def _run_dlq_worker(self) -> None:
        """DLQ-воркер с мягким завершением при закрытии цикла."""
        self._log.info("dlq_worker_started")
        try:
            while True:
                if self._closing and self._dlq_queue.empty():
                    break
                try:
                    dlq = await asyncio.wait_for(self._dlq_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                except (asyncio.CancelledError, RuntimeError, GeneratorExit):
                    break

                if self._dlq_handlers:
                    event = Event(
                        topic="dlq",
                        key=f"{dlq.event.topic}:{dlq.event.key}",
                        payload={
                            "original_topic": dlq.event.topic,
                            "original_key": dlq.event.key,
                            "payload": dlq.event.payload,
                            "handler": dlq.handler_name,
                            "attempts": dlq.attempts,
                            "error": dlq.error,
                            "ts_ms": dlq.ts_ms,
                        },
                        correlation_id=dlq.event.correlation_id,
                    )
                    for h in list(self._dlq_handlers):
                        try:
                            await h(event)
                        except Exception as exc:
                            self._log.error("dlq_handler_failed", extra={
                                "handler": getattr(h, "__name__", str(h)), "error": str(exc)
                            })

                try:
                    self._dlq_queue.task_done()
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._log.error("dlq_worker_crashed", extra={"error": str(exc)})
        finally:
            self._log.info("dlq_worker_stopped")
