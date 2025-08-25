from __future__ import annotations
from typing import Any, Dict
from .events.bus import AsyncEventBus, Event
from ..utils.logging import get_logger
from ..utils.metrics import inc

_log = get_logger("alerts")

# -- handlers -----------------------------------------------------------------

async def _on_orphaned_local_order(event: Event) -> None:
    # событие от OrdersReconciler: локально «open», на бирже ордера нет
    payload: Dict[str, Any] = event.payload or {}
    _log.error("orphaned_local_order", extra=payload)
    inc("alerts_orphaned_local_order", {"symbol": str(payload.get("symbol", "unknown"))})

async def _on_position_mismatch(event: Event) -> None:
    payload = event.payload or {}
    _log.warning("position_mismatch", extra=payload)
    inc("alerts_position_mismatch", {"symbol": str(payload.get("symbol", "unknown"))})

async def _on_balance_mismatch(event: Event) -> None:
    payload = event.payload or {}
    _log.warning("balance_mismatch", extra=payload)
    inc("alerts_balance_mismatch", {"quote": str(payload.get("quote", "unknown"))})

# -- public API ----------------------------------------------------------------

def register_alerts(bus: AsyncEventBus) -> None:
    """
    Регистрирует минимальные алерт-подписчики на системные топики
    reconciliation. Все алерты — только лог/метрики (без побочных эффектов).
    """
    bus.subscribe("reconcile.order.orphaned_local", _on_orphaned_local_order)
    bus.subscribe("reconcile.position.mismatch", _on_position_mismatch)
    bus.subscribe("reconcile.balance.mismatch", _on_balance_mismatch)
