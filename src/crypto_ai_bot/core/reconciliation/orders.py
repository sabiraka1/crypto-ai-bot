from __future__ import annotations

import time
from typing import Dict, Any, Optional, Callable, Awaitable, List

from ..brokers.base import IBroker
from ...utils.logging import get_logger


class OrdersReconciler:
    """Сверка открытых ордеров по символу с опцией авто‑отмены старых.
    Если у брокера есть метод cancel_order(order_id) — можем отменять по TTL.
    """

    def __init__(self, broker: IBroker, symbol: str, *, cancel_ttl_sec: Optional[int] = None) -> None:
        self._broker = broker
        self._symbol = symbol
        self._cancel_ttl_sec = cancel_ttl_sec
        self._log = get_logger("recon.orders")

    async def run_once(self) -> Dict[str, Any]:
        fetch: Optional[Callable[[str], Awaitable[List[dict]]]] = getattr(self._broker, "fetch_open_orders", None)  # type: ignore[attr-defined]
        if not callable(fetch):
            return {"supported": False, "open_orders": 0}
        try:
            orders = await fetch(self._symbol)  # type: ignore[misc]
            ids = [str(o.get("id")) for o in orders if isinstance(o, dict)]
            now = int(time.time() * 1000)
            cancelled: list[str] = []
            if self._cancel_ttl_sec:
                cancel: Optional[Callable[[str], Awaitable[None]]] = getattr(self._broker, "cancel_order", None)  # type: ignore[attr-defined]
                if callable(cancel):
                    for o in orders:
                        ts = int(o.get("timestamp") or now)
                        if o.get("status") == "open" and (now - ts) > self._cancel_ttl_sec * 1000:
                            try:
                                await cancel(str(o.get("id")))
                                cancelled.append(str(o.get("id")))
                            except Exception:
                                pass
            self._log.info("open_orders_checked", extra={"count": len(ids), "cancelled": len(cancelled)})
            return {"supported": True, "open_orders": len(ids), "ids": ids[:50], "cancelled": cancelled}
        except Exception as exc:
            self._log.error("open_orders_failed", extra={"error": str(exc)})
            return {"supported": True, "error": str(exc)}