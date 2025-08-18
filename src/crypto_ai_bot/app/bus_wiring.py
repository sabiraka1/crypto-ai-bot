from __future__ import annotations
import heapq
import threading
import time
from typing import Any, Callable, Dict, List, Tuple

from crypto_ai_bot.utils import metrics

Handler = Callable[[Dict[str, Any]], None]

class _PriorityBus:
    """
    Однопроцессная шина с приоритетами и стратегиями backpressure.
    publish(event) — кладёт в приоритетную очередь (меньше число = выше приоритет)
    worker-поток обрабатывает события по одному.
    """
    def __init__(self, max_queue: int = 1000) -> None:
        self._handlers: Dict[str, List[Handler]] = {}
        self._queue: List[Tuple[int, int, Dict[str, Any]]] = []
        self._counter = 0
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._stop = False
        self._dlq: List[Dict[str, Any]] = []
        self._max_queue = int(max_queue)

        # стратегии: type -> (priority, strategy)
        # strategy: "drop_oldest" | "to_dlq" | "block"
        self._policies: Dict[str, Tuple[int, str]] = {
            "dlq.error": (0, "block"),
            "order.placed": (10, "to_dlq"),
            "order.duplicate": (15, "to_dlq"),
            "metrics.ingest": (50, "drop_oldest"),
            "telegram.incoming": (20, "to_dlq"),
            "*": (30, "drop_oldest"),
        }

        self._worker = threading.Thread(target=self._loop, name="bus-worker", daemon=True)
        self._worker.start()

    def set_policy(self, event_type: str, *, priority: int, strategy: str) -> None:
        self._policies[event_type] = (int(priority), str(strategy))

    def _policy_of(self, event_type: str) -> Tuple[int, str]:
        return self._policies.get(event_type, self._policies["*"])

    def publish(self, event: Dict[str, Any]) -> None:
        et = str(event.get("type") or "")
        prio, strat = self._policy_of(et)
        with self._lock:
            if len(self._queue) >= self._max_queue:
                if strat == "drop_oldest" and self._queue:
                    heapq.heappop(self._queue)  # вытесним самый низкий по очереди
                    metrics.inc("bus_drop_oldest_total", {"type": et})
                elif strat == "to_dlq":
                    self._dlq.append({"at": int(time.time()*1000), "event": event, "reason": "backpressure"})
                    metrics.inc("bus_to_dlq_total", {"type": et})
                    return
                elif strat == "block":
                    # ждём пока освободится место
                    while len(self._queue) >= self._max_queue and not self._stop:
                        self._cv.wait(timeout=0.05)
                else:
                    # по умолчанию — в DLQ
                    self._dlq.append({"at": int(time.time()*1000), "event": event, "reason": "overflow"})
                    return
            self._counter += 1
            heapq.heappush(self._queue, (prio, self._counter, event))
            self._cv.notify()

    def subscribe(self, type_: str, handler: Handler) -> None:
        self._handlers.setdefault(type_, []).append(handler)

    def _dispatch(self, ev: Dict[str, Any]) -> None:
        et = str(ev.get("type") or "")
        for h in self._handlers.get(et, []):
            try:
                h(ev)
            except Exception as e:
                self._dlq.append({"at": int(time.time()*1000), "event": ev, "reason": f"handler_error:{type(e).__name__}"})
                metrics.inc("bus_handler_error_total", {"type": et})

    def _loop(self):
        while not self._stop:
            with self._lock:
                while not self._queue and not self._stop:
                    self._cv.wait(timeout=0.05)
                if self._stop:
                    break
                _, _, ev = heapq.heappop(self._queue)
                self._cv.notify()
            self._dispatch(ev)

    def health(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "queue": len(self._queue),
                "dlq_size": len(self._dlq),
                "status": "ok" if not self._stop else "stopped",
            }

    def dlq_dump(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._dlq[-int(limit):])

    def stop(self) -> None:
        with self._lock:
            self._stop = True
            self._cv.notify_all()
        self._worker.join(timeout=1.0)

def make_bus() -> _PriorityBus:
    return _PriorityBus(max_queue=1000)

def snapshot_quantiles() -> Dict[str, Any]:
    # заглушка под ваш экспорт квантилей — если есть отдельный модуль метрик, оставим так
    return {}
