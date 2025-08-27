from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from ..brokers.base import IBroker, OrderDTO
from ..events.bus import AsyncEventBus
from ..risk.manager import RiskManager
from ..risk.protective_exits import ProtectiveExits
from ..storage.facade import Storage
from ..strategies.manager import StrategyManager
from ..strategies.base import StrategyContext
from ...utils.logging import get_logger
from ...utils.ids import make_client_order_id
from ...utils.time import now_ms

_log = get_logger("usecase.eval_and_execute")


async def _build_market_context(*, broker: IBroker, symbol: str) -> Dict[str, Any]:
    t = await broker.fetch_ticker(symbol)
    spread = float((t.ask - t.bid) / t.last * 100) if t.last and t.ask and t.bid else 0.0
    return {"ticker": {"last": t.last, "bid": t.bid, "ask": t.ask, "timestamp": t.timestamp}, "spread": spread}


def _normalize_risk_result(result: Any) -> Tuple[bool, str]:
    if result is None:
        return True, ""
    if isinstance(result, tuple) and len(result) >= 1:
        ok = bool(result[0])
        reason = str(result[1]) if len(result) > 1 and result[1] is not None else ""
        return ok, reason
    if isinstance(result, dict):
        if "allowed" in result:
            ok = bool(result.get("allowed"))
            reasons = result.get("reasons") or []
            return ok, ";".join(map(str, reasons)) if isinstance(reasons, (list, tuple)) else str(reasons)
        if "ok" in result:
            return bool(result.get("ok")), str(result.get("reason") or "")
    return True, ""


async def eval_and_execute(
    *,
    symbol: str,
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    exchange: str,
    fixed_quote_amount: Decimal,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
    force_action: Optional[str] = None,
    risk_manager: Optional[RiskManager] = None,
    protective_exits: Optional[ProtectiveExits] = None,
) -> Dict[str, Any]:
    ctx = await _build_market_context(broker=broker, symbol=symbol)

    manager = StrategyManager()
    decision, explain = (force_action, {"reason": "forced"}) if force_action else manager.decide(symbol=symbol, exchange=exchange, context=ctx, mode="first")

    if risk_manager:
        raw = await risk_manager.check(symbol=symbol, action=decision, evaluation={"ctx": ctx, "explain": explain})
        ok, reason = _normalize_risk_result(raw)
        if not ok:
            await bus.publish("trade.blocked", {"symbol": symbol, "reason": reason}, key=symbol)
            return {"executed": False, "why": f"blocked:{reason}"}

    order: Optional[OrderDTO] = None
    try:
        if decision == "buy":
            cid = make_client_order_id(exchange, f"{symbol}:buy:{now_ms()}")
            order = await broker.create_market_buy_quote(symbol=symbol, quote_amount=fixed_quote_amount, client_order_id=cid)
        elif decision == "sell":
            pos = storage.positions.get_position(symbol)
            if pos.base_qty and pos.base_qty > 0:
                cid = make_client_order_id(exchange, f"{symbol}:sell:{now_ms()}")
                order = await broker.create_market_sell_base(symbol=symbol, base_amount=pos.base_qty, client_order_id=cid)
    except Exception as exc:
        _log.error("place_order_failed", extra={"error": str(exc)})
        await bus.publish("trade.failed", {"symbol": symbol, "error": str(exc)}, key=symbol)
        return {"executed": False, "why": f"place_order_failed:{exc}"}

    if protective_exits:
        try:
            await protective_exits.ensure(symbol=symbol)
        except Exception as exc:
            _log.error("exits_ensure_failed", extra={"error": str(exc)})

    await bus.publish(
        "trade.completed",
        {
            "symbol": symbol,
            "decision": decision,
            "executed": bool(order),
            "order_id": getattr(order, "id", None),
            "amount": str(getattr(order, "amount", "")) if order else "",
            "filled": str(getattr(order, "filled", "")) if order else "",
        },
        key=symbol,
    )

    return {"executed": bool(order), "decision": decision, "order": order}
