from __future__ import annotations

from typing import Any, Dict
from ..events.bus import Event, AsyncEventBus
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("alerts.reconcile")

async def _on_stale(evt: Event) -> None:
    # evt.payload ожидается вида:
    # { "symbol": "BTC/USDT", "id": "...", "side": "buy|sell",
    #   "age_ms": 123456, "remaining": "0.001" }
    p: Dict[str, Any] = evt.payload or {}
    _log.warning("stale_order_detected", extra=p)
    inc("alerts_reconcile_stale", {
        "symbol": str(p.get("symbol", "?")),
        "side": str(p.get("side", "?")),
    })

def attach(bus: AsyncEventBus) -> None:
    # подписываемся на события, которые шлёт OrdersReconciler
    bus.subscribe("reconcile.order_stale", _on_stale)
