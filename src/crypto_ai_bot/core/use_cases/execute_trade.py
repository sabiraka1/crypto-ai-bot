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
from ..brokers.symbols import parse_symbol
from ...utils.logging import get_logger
from ...utils.ids import make_client_order_id
from ...utils.time import now_ms
from .partial_fills import PartialFillHandler

_log = get_logger("usecase.execute")


async def build_market_context(*, broker: IBroker, symbol: str) -> Dict[str, Any]:
    t = await broker.fetch_ticker(symbol)
    spread = float((t.ask - t.bid) / t.last * 100) if t.last and t.ask and t.bid else 0.0
    return {"ticker": {"last": t.last, "bid": t.bid, "ask": t.ask, "timestamp": t.timestamp}, "spread": spread}


async def evaluate(*, manager: StrategyManager, symbol: str, exchange: str, ctx: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    d, e = manager.decide(symbol=symbol, exchange=exchange, context=ctx, mode="first")
    return d, e


async def execute_trade(
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
    """Полный цикл исполнения одной попытки."""
    # 1) market ctx + decision
    ctx = await build_market_context(broker=broker, symbol=symbol)
    manager = StrategyManager()
    decision, explain = (force_action, {"reason": "forced"}) if force_action else await evaluate(manager=manager, symbol=symbol, exchange=exchange, ctx=ctx)

    # 2) risk checks
    if risk_manager:
        ok, reason = await risk_manager.check(symbol=symbol, action=decision, evaluation={"ctx": ctx, "explain": explain})
        if not ok:
            await bus.publish("trade.blocked", {"symbol": symbol, "reason": reason}, key=symbol)
            return {"executed": False, "why": f"blocked:{reason}"}

    # 3) place order
    order: Optional[OrderDTO] = None
    if decision == "buy":
        cid = make_client_order_id(exchange, f"{symbol}:buy:{now_ms()}")
        order = await broker.create_market_buy_quote(symbol=symbol, quote_amount=fixed_quote_amount, client_order_id=cid)
    elif decision == "sell":
        pos = storage.positions.get_position(symbol)
        if pos.base_qty and pos.base_qty > 0:
            cid = make_client_order_id(exchange, f"{symbol}:sell:{now_ms()}")
            order = await broker.create_market_sell_base(symbol=symbol, base_amount=pos.base_qty, client_order_id=cid)

    # 4) partial fills (если есть order и он не полностью исполнен)
    if order and (order.filled < order.amount or (order.status or "").lower() != "closed"):
        pf = PartialFillHandler(bus)
        try:
            follow = await pf.handle(order, broker)
            if follow:
                order = follow  # берём последний ордер как итоговый
        except Exception as exc:
            _log.error("partial_fills_failed", extra={"error": str(exc)})

    # 5) exits ensure
    if protective_exits:
        try:
            await protective_exits.ensure(symbol=symbol)
        except Exception as exc:
            _log.error("exits_ensure_failed", extra={"error": str(exc)})

    # 6) финальное событие
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
