from __future__ import annotations

from typing import Dict, Any, Optional, Callable, Awaitable, List

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.utils.logging import get_logger


class OrdersReconciler:
    def __init__(self, broker: IBroker, symbol: str) -> None:
        self._broker = broker
        self._symbol = symbol
        self._log = get_logger("recon.orders")

    async def run_once(self) -> Dict[str, Any]:
        fetch: Optional[Callable[[str], Awaitable[List[dict]]]] = getattr(self._broker, "fetch_open_orders", None)  # type: ignore[attr-defined]
        if not callable(fetch):
            return {"supported": False, "open_orders": 0}
        try:
            orders = await fetch(self._symbol)  # type: ignore[misc]
            ids = [str(o.get("id")) for o in orders if isinstance(o, dict)]
            self._log.info("open_orders_checked", extra={"count": len(ids)})
            return {"supported": True, "open_orders": len(ids), "ids": ids[:50]}
        except Exception as exc:
            self._log.error("open_orders_failed", extra={"error": str(exc)})
            return {"supported": True, "error": str(exc)}
