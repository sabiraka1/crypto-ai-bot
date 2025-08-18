from __future__ import annotations
from typing import Callable, Dict, Any, List, Optional
import threading
import time


class EventBus:
    """
    Простая синхронная шина событий с приоритетами обработчиков,
    ограниченным DLQ и health().
    """
    def __init__(self, *, max_dlq: int = 10_000):
        self._subs: Dict[str, List[tuple[int, Callable[[str, Dict[str, Any]], None]]]] = {}
        self._lock = threading.RLock()
        self._dlq: List[Dict[str, Any]] = []
        self._max_dlq = int(max(100, max_dlq))
        self._running = True

    # подписка с приоритетом (меньше = раньше)
    def subscribe(self, topic: str, handler: Callable[[str, Dict[str, Any]], None], *, priority: int = 100) -> None:
        with self._lock:
            self._subs.setdefault(topic, []).append((priority, handler))
            self._subs[topic].sort(key=lambda x: x[0])

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """
        Синхронно вызываем обработчики. Исключения — в DLQ (с ограничением).
        """
        with self._lock:
            handlers = list(self._subs.get(topic, ()))
        for _, h in handlers:
            try:
                h(topic, payload)
            except Exception as e:
                self._push_dlq({"ts": int(time.time()), "topic": topic, "payload": payload, "error": repr(e)})

    # утилиты
    def _push_dlq(self, item: Dict[str, Any]) -> None:
        with self._lock:
            self._dlq.append(item)
            overflow = len(self._dlq) - self._max_dlq
            if overflow > 0:
                # отбрасываем самый старый хвост
                del self._dlq[0:overflow]

    def drain_dlq(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._dlq[-max(1, limit):])

    def health(self) -> Dict[str, Any]:
        with self._lock:
            return {"running": self._running, "dlq_size": len(self._dlq)}

    def stop(self) -> None:
        with self._lock:
            self._running = False


def build_event_bus(cfg) -> EventBus:
    max_dlq = getattr(cfg, "EVENTBUS_DLQ_MAX", 10_000)
    return EventBus(max_dlq=max_dlq)
