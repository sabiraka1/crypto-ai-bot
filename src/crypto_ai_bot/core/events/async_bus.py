# src/crypto_ai_bot/core/events/async_bus.py
from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from crypto_ai_bot.utils import metrics

_Strategy = str  # "block" | "drop_oldest" | "keep_latest"

class AsyncEventBus:
    """
    Асинхронная шина событий с backpressure:
      - block:     ждать пока освободится место
      - drop_oldest: удалить старое и положить новое
      - keep_latest:  сохранить только последнее (новое), старые дропнуть
    DLQ (dead letter queue) для ошибок обработчиков.
    """

    def __init__(self, *, strategy_map: Dict[str, Dict[str, Any]], dlq_max: int = 1000, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.loop = loop or asyncio.get_event_loop()
        self.strategy_map = strategy_map or {}
        self.dlq = deque(maxlen=int(dlq_max))
        self.handlers: Dict[str, List[Callable[[Dict[str, Any]], Any]]] = {}
        self._queues: Dict[str, asyncio.Queue] = {}
        self._tasks: List[asyncio.Task] = []
        self._running = False

    # ---------- public API ----------

    def subscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        self.handlers.setdefault(event_type, []).append(handler)
        # ленивая инициализация очереди под тип
        self._ensure_queue(event_type)

    def publish(self, event: Dict[str, Any]) -> None:
        et = str(event.get("type") or "")
        if not et:
            return
        q = self._ensure_queue(et)
        strat, qsize = self._strategy_for(et)
        put_coro = self._put_with_strategy(q, event, strat, qsize)

        try:
            # потокобезопасный вызов из sync-кода
            asyncio.run_coroutine_threadsafe(put_coro, self.loop)
        except RuntimeError:
            # если луп не запущен — просто дропнем (не роняем основной поток)
            metrics.inc("bus_publish_drop_total", {"reason": "loop_not_running", "type": et})

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for etype in list(self._queues.keys()):
            self._tasks.append(self.loop.create_task(self._worker(etype), name=f"bus-worker:{etype}"))

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()

    def health(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "status": "ok",
            "types": {},
            "dlq_size": len(self.dlq),
        }
        for et, q in self._queues.items():
            out["types"][et] = {"qsize": q.qsize(), **self._strategy_map_view(et)}
        return out

    def dlq_dump(self, limit: int = 50) -> List[Dict[str, Any]]:
        n = max(1, min(int(limit), len(self.dlq)))
        return list(self.dlq)[-n:]

    # ---------- internals ----------

    def _ensure_queue(self, event_type: str) -> asyncio.Queue:
        if event_type not in self._queues:
            strat, qsize = self._strategy_for(event_type)
            self._queues[event_type] = asyncio.Queue(maxsize=int(qsize))
        return self._queues[event_type]

    def _strategy_for(self, event_type: str) -> tuple[_Strategy, int]:
        cfg = self.strategy_map.get(event_type) or {}
        strat = str(cfg.get("strategy") or "block")
        qsize = int(cfg.get("queue_size") or 1024)
        return strat, qsize

    def _strategy_map_view(self, event_type: str) -> Dict[str, Any]:
        strat, qsize = self._strategy_for(event_type)
        return {"strategy": strat, "queue_size": qsize}

    async def _put_with_strategy(self, q: asyncio.Queue, item: Dict[str, Any], strat: _Strategy, qsize: int) -> None:
        et = str(item.get("type") or "")
        if strat == "block":
            # дождаться места
            await q.put(item)
            metrics.inc("bus_enqueued_total", {"type": et, "strategy": "block"})
            return

        if strat == "drop_oldest":
            if q.full():
                try:
                    _ = q.get_nowait()
                    q.task_done()
                    metrics.inc("bus_dropped_total", {"type": et, "strategy": "drop_oldest"})
                except asyncio.QueueEmpty:
                    pass
            await q.put(item)
            metrics.inc("bus_enqueued_total", {"type": et, "strategy": "drop_oldest"})
            return

        if strat == "keep_latest":
            # выбрасываем всё старое, кладём только новое
            while not q.empty():
                try:
                    _ = q.get_nowait()
                    q.task_done()
                except asyncio.QueueEmpty:
                    break
            await q.put(item)
            metrics.inc("bus_enqueued_total", {"type": et, "strategy": "keep_latest"})
            return

        # неизвестная стратегия → fallback block
        await q.put(item)
        metrics.inc("bus_enqueued_total", {"type": et, "strategy": "block"})

    async def _worker(self, event_type: str) -> None:
        q = self._queues[event_type]
        while self._running:
            try:
                item = await q.get()
            except asyncio.CancelledError:
                break
            except Exception:
                continue

            try:
                handlers = list(self.handlers.get(event_type, []))
                if not handlers:
                    # нет обработчиков — считаем доставленным
                    metrics.inc("bus_delivered_total", {"type": event_type, "handlers": "0"})
                    q.task_done()
                    continue

                delivered = 0
                for h in handlers:
                    try:
                        if asyncio.iscoroutinefunction(h):
                            await h(item)
                        else:
                            # исполняем sync-обработчик в default executor
                            loop = asyncio.get_running_loop()
                            await loop.run_in_executor(None, h, item)
                        delivered += 1
                    except Exception as e:
                        # отправляем в DLQ
                        self.dlq.append({"type": event_type, "error": f"{type(e).__name__}: {e}", "event": item})
                        metrics.inc("bus_dlq_total", {"type": event_type})
                metrics.inc("bus_delivered_total", {"type": event_type, "handlers": str(delivered)})
            finally:
                q.task_done()
