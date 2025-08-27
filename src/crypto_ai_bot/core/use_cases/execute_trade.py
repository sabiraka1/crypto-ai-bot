from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from ..brokers.base import IBroker, OrderDTO
from ..events.bus import AsyncEventBus
from ..risk.manager import RiskManager
from ..risk.protective_exits import ProtectiveExits
from ..storage.facade import Storage
from ...utils.logging import get_logger
from ...utils.ids import make_client_order_id
from ...utils.time import now_ms
from ...utils.metrics import inc

_log = get_logger("usecase.execute_trade")


def _normalize_risk_result(result: Any) -> Tuple[bool, str]:
    """Единый формат результата risk.check: (ok, reason).
    Поддерживаем варианты: tuple, dict с ok/allowed/reason/reasons.
    """
    if result is None:
        return True, ""
    if isinstance(result, tuple) and len(result) >= 1:
        ok = bool(result[0])
        reason = str(result[1]) if len(result) > 1 and result[1] is not None else ""
        return ok, reason
    if isinstance(result, dict):
        # Новый формат: {"ok": bool, "reasons": [..]}
        if "ok" in result:
            ok = bool(result.get("ok"))
            if "reasons" in result and isinstance(result["reasons"], (list, tuple)):
                reason = ";".join(map(str, result["reasons"]))
            else:
                reason = str(result.get("reason") or "")
            return ok, reason
        # Старый альтернативный ключ:
        if "allowed" in result:
            ok = bool(result.get("allowed"))
            reasons = result.get("reasons") or []
            if isinstance(reasons, (list, tuple)):
                return ok, ";".join(map(str, reasons))
            return ok, str(reasons)
    return True, ""


async def execute_trade(
    *,
    symbol: str,
    side: str,  # "buy" | "sell"
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    exchange: str,
    quote_amount: Optional[Decimal] = None,  # для BUY
    base_amount: Optional[Decimal] = None,   # для SELL
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
    risk_manager: Optional[RiskManager] = None,
    protective_exits: Optional[ProtectiveExits] = None,
) -> Dict[str, Any]:
    """Единичное исполнение торгового действия с идемпотентностью и проверкой рисков."""
    side = (side or "").lower()
    if side not in ("buy", "sell"):
        return {"executed": False, "why": "invalid_side"}

    # --- риск-гейт -------------------------------------------------------------
    if risk_manager:
        raw = await risk_manager.check(symbol=symbol, action=side, evaluation={"explain": "execute_trade"})
        ok, reason = _normalize_risk_result(raw)
        if not ok:
            inc("orders_blocked_total", reason=(reason or "unspecified"))
            await bus.publish("trade.blocked", {"symbol": symbol, "reason": reason, "side": side}, key=symbol)
            return {"executed": False, "why": f"blocked:{reason}"}

    # --- размещение ордера -----------------------------------------------------
    order: Optional[OrderDTO] = None
    try:
        if side == "buy":
            if quote_amount is None or quote_amount <= 0:
                return {"executed": False, "why": "invalid_quote_amount"}
            cid = make_client_order_id(exchange, f"{symbol}:buy:{now_ms()}")
            order = await broker.create_market_buy_quote(symbol=symbol, quote_amount=quote_amount, client_order_id=cid)

        else:  # sell
            amt = base_amount
            if amt is None:
                # если не задано — берём всю локальную позицию
                pos = storage.positions.get_position(symbol)
                amt = pos.base_qty
            if not amt or amt <= 0:
                return {"executed": False, "why": "no_base_to_sell"}
            cid = make_client_order_id(exchange, f"{symbol}:sell:{now_ms()}")
            order = await broker.create_market_sell_base(symbol=symbol, base_amount=amt, client_order_id=cid)

    except Exception as exc:
        inc("errors_total", kind="execute_trade_failed")
        _log.error("execute_trade_failed", extra={"error": str(exc), "side": side})
        await bus.publish("trade.failed", {"symbol": symbol, "error": str(exc), "side": side}, key=symbol)
        return {"executed": False, "why": f"place_order_failed:{exc}"}

    if order:
        inc("orders_placed_total", side=(order.side or side))

    # --- защитные выходы -------------------------------------------------------
    if protective_exits and side == "buy":
        try:
            await protective_exits.ensure(symbol=symbol)
        except Exception as exc:
            inc("errors_total", kind="exits_ensure_failed")
            _log.error("exits_ensure_failed", extra={"error": str(exc)})

    await bus.publish(
        "trade.completed",
        {
            "symbol": symbol,
            "decision": side,
            "executed": bool(order),
            "order_id": getattr(order, "id", None),
            "amount": str(getattr(order, "amount", "")) if order else "",
            "filled": str(getattr(order, "filled", "")) if order else "",
        },
        key=symbol,
    )
    return {"executed": bool(order), "decision": side, "order": order}