# src/crypto_ai_bot/core/events/bus.py
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from typing import Any, Callable, Deque, Dict, List, Tuple
import time
import traceback

from crypto_ai_bot.utils import metrics


Handler = Callable[[Any], None]


def _event_type_of(event: Any) -> str:
    # Пытаемся аккуратно определить тип события
    if isinstance(event, dict):
        et = event.get("type") or event.get("event_type")
        if not et:
            raise ValueError("event dict must contain 'type' or 'event_type'")
        return str(et)
    # dataclass/объект с атрибутом
    for attr in ("event_type", "type", "__class__.__name__"):
        if hasattr(event, attr):
            val = getattr(event, attr)
            if isinstance(val, str):
                return val
    # fallback — имя класса
    return event.__class__.__name__


@dataclass
class BusStats:
    delivered_total: int = 0
    handler_errors_total: int = 0
    dlq_size: int = 0


class Bus:
    """
    Простой синхронный шина событий (in-proc).
    - publish() вызывает подписчиков в текущем потоке по очереди.
    - Ошибки хэндлеров не прерывают доставку: считаются, складываются в DLQ.
    - Поддержка wildcard-подписки на '*'.
    Использование: глобальный экземпляр создаётся приложением и передаётся в нужные слои.
    """

    def __init__(self, *, dlq_max: int = 1000) -> None:
        self._subs: Dict[str, List[Handler]] = defaultdict(list)
        self._subs_all: List[Handler] = []  # подписки на '*'
        self._dlq: Deque[Tuple[str, Any, str]] = deque(maxlen=max(1, dlq_max))  # (event_type, event, err)
        self._stats = BusStats()

    # ---------- подписки ----------

    def subscribe(self, event_type: str, handler: Handler) -> None:
        if event_type == "*":
            self._subs_all.append(handler)
        else:
            self._subs[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        try:
            if event_type == "*":
                self._subs_all.remove(handler)
            else:
                self._subs[event_type].remove(handler)
        except ValueError:
            pass

    # ---------- публикация ----------

    def publish(self, event: Any) -> None:
        et = _event_type_of(event)
        handlers = list(self._subs.get(et, ())) + list(self._subs_all)
        if not handlers:
            # нет подписчиков — просто считаем доставленным
            self._stats.delivered_total += 1
            metrics.inc("events_published_total", {"type": et, "handlers": "0"})
            return

        metrics.inc("events_published_total", {"type": et, "handlers": str(len(handlers))})
        t0 = time.perf_counter()
        for h in handlers:
            try:
                h(event)
            except Exception as e:
                self._stats.handler_errors_total += 1
                tb = traceback.format_exc(limit=3)
                self._dlq.append((et, event, f"{type(e).__name__}: {e}\n{tb}"))
                metrics.inc("events_handler_errors_total", {"type": et})
        self._stats.delivered_total += 1
        metrics.observe("events_dispatch_seconds", time.perf_counter() - t0, {"type": et})

        metrics.observe("events_dlq_size", float(len(self._dlq)), {"bus": "sync"})

    # ---------- состояние / DLQ ----------

    def dlq_dump(self, limit: int = 50) -> List[Dict[str, Any]]:
        items = list(self._dlq)[-limit:]
        out: List[Dict[str, Any]] = []
        for et, ev, err in items:
            out.append({"type": et, "event": ev, "error": err})
        return out

    def health(self) -> Dict[str, Any]:
        # для /health можно вернуть краткое состояние
        st = {
            "delivered_total": self._stats.delivered_total,
            "handler_errors_total": self._stats.handler_errors_total,
            "dlq_size": len(self._dlq),
            "status": "healthy" if len(self._dlq) == 0 else "degraded",
        }
        return st
