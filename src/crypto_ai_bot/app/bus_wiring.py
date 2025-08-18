# src/crypto_ai_bot/app/bus_wiring.py
from collections import deque
from typing import Callable, Dict, Any, DefaultDict, List
from collections import defaultdict
import time

from crypto_ai_bot.utils.metrics import inc, gauge

class EventBus:
    def __init__(self, max_dlq: int = 2000):
        self._subs: DefaultDict[str, List[Callable[[str, Dict[str, Any]], None]]] = defaultdict(list)
        self._dlq = deque(maxlen=max_dlq)
        self._running = True

    def subscribe(self, topic: str, handler: Callable[[str, Dict[str, Any]], None]) -> None:
        self._subs[topic].append(handler)

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        if not self._running:
            return
        handlers = list(self._subs.get(topic, []))
        start = time.perf_counter()
        for h in handlers:
            try:
                h(topic, payload)
            except Exception as e:
                self._dlq.append({"ts": time.time(), "topic": topic, "payload": payload, "error": repr(e)})
                inc("bus_dlq_add", {"topic": topic})
        dur = time.perf_counter() - start
        inc("bus_publish_total", {"topic": topic})
        gauge("bus_publish_last_seconds", dur, {"topic": topic})

    def stop(self):
        self._running = False

    def health(self) -> Dict[str, Any]:
        return {"running": self._running, "dlq_size": len(self._dlq)}

    def dlq_dump(self, limit: int = 100) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        out = list(self._dlq)[-limit:]
        return out

def build_event_bus(cfg) -> EventBus:
    bus = EventBus(max_dlq=getattr(cfg, "BUS_DLQ_MAX", 2000))
    return bus
