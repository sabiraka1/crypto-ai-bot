from __future__ import annotations

from typing import Dict, Any, Optional, Callable, Awaitable, List

from ..brokers.base import IBroker
from ...utils.logging import get_logger
from ...utils.time import now_ms
from ...utils.metrics import inc


class OrdersReconciler:
    """Сверка открытых ордеров + авто‑cancel старых по TTL.

    Требования к брокеру (опциональные методы):
      • fetch_open_orders(symbol) -> List[dict]
      • cancel_order(symbol, order_id) -> Any
    Если методы отсутствуют, просто диагностируем.
    """

    def __init__(self, broker: IBroker, symbol: str, *, ttl_sec: Optional[int] = None) -> None:
        self._broker = broker
        self._symbol = symbol
        self._log = get_logger("recon.orders")
        self._ttl_ms = None if ttl_sec is None else max(0, int(ttl_sec)) * 1000

    async def run_once(self) -> Dict[str, Any]:
        fetch: Optional[Callable[[str], Awaitable[List[dict]]]] = getattr(self._broker, "fetch_open_orders", None)  # type: ignore[attr-defined]
        if not callable(fetch):
            return {"supported": False, "open_orders": 0}
        try:
            orders = await fetch(self._symbol)  # type: ignore[misc]
            ids = []
            canceled = []
            now = now_ms()
            for o in orders or []:
                oid = str(o.get("id")) if isinstance(o, dict) else None
                ts = int(o.get("timestamp") or 0) if isinstance(o, dict) else 0
                if oid:
                    ids.append(oid)
                # авто‑cancel по TTL
                if self._ttl_ms and oid and ts and (now - ts) > self._ttl_ms:
                    cancel_fn: Optional[Callable[[str, str], Awaitable[Any]]] = getattr(self._broker, "cancel_order", None)  # type: ignore[attr-defined]
                    if callable(cancel_fn):
                        try:
                            await cancel_fn(self._symbol, oid)  # type: ignore[misc]
                            canceled.append(oid)
                            inc("open_orders_canceled_total", {"symbol": self._symbol})
                            self._log.error("order_auto_cancelled", extra={"symbol": self._symbol, "order_id": oid, "age_ms": now - ts})
                        except Exception as exc:  # не падаем всей свёркой
                            self._log.error("order_cancel_failed", extra={"symbol": self._symbol, "order_id": oid, "error": str(exc)})
            self._log.info("open_orders_checked", extra={"count": len(ids), "canceled": len(canceled)})
            return {"supported": True, "open_orders": len(ids), "canceled": canceled[:50], "ids": ids[:50]}
        except Exception as exc:
            self._log.error("open_orders_failed", extra={"error": str(exc)})
            return {"supported": True, "error": str(exc)}