# src/crypto_ai_bot/app/bus_wiring.py
from __future__ import annotations

import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.core.events.factory import get_backpressure_conf


# -------- Quantiles (rolling) --------
@dataclass
class _Q:
    last: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    count: int = 0


class _Quantiles:
    """Очень лёгкая RQ-метрика по ключу: поддерживает p95/p99."""
    def __init__(self, maxlen: int = 2048) -> None:
        self._buckets: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=maxlen))
        self._lock = threading.RLock()

    def observe(self, key: str, v: float) -> None:
        with self._lock:
            self._buckets[key].append(float(v))

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        with self._lock:
            for k, q in self._buckets.items():
                if not q:
                    out[k] = {"count": 0, "p95": 0.0, "p99": 0.0}
                    continue
                xs = sorted(q)
                n = len(xs)
                p95 = xs[min(n - 1, int(0.95 * (n - 1)))]
                p99 = xs[min(n - 1, int(0.99 * (n - 1)))]
                out[k] = {"count": float(n), "p95": float(p95 * 1000.0), "p99": float(p99 * 1000.0)}  # в мс
        return out


_RQ = _Quantiles()


def observe_decision_latency(sec: float, *, symbol: str, timeframe: str) -> None:
    _RQ.observe(f"decision:{symbol}:{timeframe}", float(sec))


def observe_order_latency(sec: float, *, symbol: str, timeframe: str, side: str) -> None:
    _RQ.observe(f"order:{symbol}:{timeframe}:{side}", float(sec))


def observe_flow_latency(sec: float, *, symbol: str, timeframe: str) -> None:
    _RQ.observe(f"flow:{symbol}:{timeframe}", float(sec))


def snapshot_quantiles() -> Dict[str, Dict[str, float]]:
    return _RQ.snapshot()


# --------- Simple Async-ish Bus with backpressure ---------
Handler = Callable[[Dict[str, Any]], None]


class _Bus:
    def __init__(self) -> None:
        self._subs: Dict[str, List[Handler]] = defaultdict(list)
        self._dlq: Deque[Dict[str, Any]] = deque(maxlen=10_000)
        self._lock = threading.RLock()
        self._queued: Deque[Tuple[int, Dict[str, Any]]] = deque(maxlen=50_000)  # (priority, event)

    def subscribe(self, type_: str, handler: Handler) -> None:
        with self._lock:
            self._subs[type_].append(handler)

    def _apply_backpressure(self, ev: Dict[str, Any]) -> Optional[str]:
        """Возвращает причину дропа, если событие не принято."""
        t = ev.get("type", "Unknown")
        conf = get_backpressure_conf(str(t))
        policy = conf.get("policy", "drop_oldest")
        max_q = int(conf.get("max_queue", 2000))
        prio = int(conf.get("priority", 5))
        ev["priority"] = prio  # сохраняем приоритет в самом событии

        # Учтём только события этого типа при лимите
        same_type = sum(1 for _, e in self._queued if e.get("type") == t)
        if same_type < max_q:
            return None

        if policy == "drop_new":
            return "drop_new"
        if policy == "drop_oldest":
            # выкинем самый старый такого же типа
            for i, (_p, e) in enumerate(self._queued):
                if e.get("type") == t:
                    try:
                        del self._queued[i]
                        break
                    except Exception:
                        break
            return None
        if policy == "block":
            # упрощённо: принимаем (не блокируем event loop)
            return None
        if policy == "coalesce":
            # если уже есть такое событие без уникального ключа — просто заменим хвостовое
            for i in range(len(self._queued) - 1, -1, -1):
                _p, e = self._queued[i]
                if e.get("type") == t:
                    self._queued[i] = (prio, ev)
                    return "coalesced"
            return None
        return None

    def publish(self, ev: Dict[str, Any]) -> None:
        with self._lock:
            reason = self._apply_backpressure(ev)
            if reason == "drop_new":
                self._dlq.append(ev)
                metrics.inc("events_dlq_total", {"reason": "drop_new", "type": str(ev.get("type"))})
                return
            # приоритет: вставляем по возрастанию priority
            prio = int(ev.get("priority", 5))
            inserted = False
            for i, (p, _e) in enumerate(self._queued):
                if prio < p:
                    self._queued.insert(i, (prio, ev))
                    inserted = True
                    break
            if not inserted:
                self._queued.append((prio, ev))

        # синхронная «доставка»: пробуем доставить сразу
        handlers = list(self._subs.get(ev.get("type", ""), []))
        for h in handlers:
            try:
                h(ev)
            except Exception:
                self._dlq.append(ev)
                metrics.inc("events_dlq_total", {"reason": "handler_error", "type": str(ev.get("type"))})

    def health(self) -> Dict[str, Any]:
        with self._lock:
            return {"status": "ok", "dlq_size": len(self._dlq), "queued": len(self._queued)}

    # совместимость
    def __len__(self) -> int:
        with self._lock:
            return len(self._queued)


def make_bus():
    return _Bus()
