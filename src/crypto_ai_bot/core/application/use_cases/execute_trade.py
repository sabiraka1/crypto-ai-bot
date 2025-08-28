from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker, OrderDTO
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskInputs
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.ids import make_client_order_id
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("usecase.execute_trade")


async def execute_trade(
    *,
    symbol: str,
    side: str,
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    exchange: str,
    quote_amount: Optional[Decimal] = None,
    base_amount: Optional[Decimal] = None,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
    risk_manager: Optional[RiskManager] = None,
    protective_exits: Optional[ProtectiveExits] = None,
    force_action: Optional[str] = None,  # Added for compatibility with new logic
) -> Dict[str, Any]:
    """
    Execute trade with risk management and protective exits.
    
    Key changes:
    - Now fetches ticker to calculate spread for risk assessment
    - Uses RiskInputs dataclass for risk manager
    - Supports force_action parameter to bypass risk checks
    - Returns action-based response (buy/sell/hold/skip)
    """
    side = (side or "").lower()
    
    # Get current market data for risk assessment
    ticker = await broker.fetch_ticker(symbol)
    mid_price = (ticker.bid + ticker.ask) / Decimal("2") if ticker.bid and ticker.ask else (ticker.last or Decimal("0"))
    spread_pct = ((ticker.ask - ticker.bid) / mid_price) if ticker.bid and ticker.ask and mid_price > 0 else Decimal("0")
    
    # Get position and trading history
    pos = storage.positions.get_position(symbol)
    position_base = pos.base_qty if pos else Decimal("0")
    
    # Get recent orders count (last 60 minutes)
    recent_orders = 0
    if hasattr(storage, 'trades') and hasattr(storage.trades, 'count_orders_last_minutes'):
        recent_orders = storage.trades.count_orders_last_minutes(symbol, 60)
    
    # Get daily PnL
    pnl_daily = Decimal("0")
    if hasattr(storage, 'trades') and hasattr(storage.trades, 'daily_pnl_quote'):
        pnl_daily = storage.trades.daily_pnl_quote(symbol)
    
    # Check cooldown status
    cooldown_active = False
    if hasattr(storage, 'cooldowns') and hasattr(storage.cooldowns, 'is_active'):
        cooldown_active = storage.cooldowns.is_active(symbol)
    
    # Risk management check using new RiskInputs structure
    if risk_manager and not force_action:
        risk_inputs = RiskInputs(
            spread_pct=spread_pct,
            position_base=position_base,
            recent_orders=recent_orders,
            pnl_daily_quote=pnl_daily,
            cooldown_active=cooldown_active
        )
        
        risk_result = await risk_manager.check(risk_inputs)
        
        # Handle risk result - expecting dict with 'ok' and 'deny_reasons'
        if isinstance(risk_result, dict):
            if not risk_result.get("ok", True):
                reasons = risk_result.get("deny_reasons", ["unspecified"])
                reason_str = ";".join(reasons) if isinstance(reasons, list) else str(reasons)
                inc("orders_blocked_total", reason=reason_str)
                await bus.publish("trade.blocked", {"symbol": symbol, "reason": reason_str, "side": side}, key=symbol)
                return {"action": "skip", "executed": False, "reasons": reasons, "why": f"blocked:{reason_str}"}
    
    # Determine action based on side and position
    if side not in ("buy", "sell"):
        # Auto-determine action based on position
        if position_base <= 0:
            side = "buy"
        elif position_base > 0:
            side = "sell"
        else:
            return {"action": "hold", "executed": False, "why": "no_clear_action"}
    
    # Check idempotency for buy orders
    if side == "buy":
        bucket = (now_ms() // idempotency_bucket_ms) * idempotency_bucket_ms
        idem_key = f"{symbol}:buy:{bucket}"
        if hasattr(storage, 'idempotency') and hasattr(storage.idempotency, 'check_and_store'):
            if not storage.idempotency.check_and_store(idem_key, ttl_sec=idempotency_ttl_sec, default_bucket_ms=idempotency_bucket_ms):
                return {"action": "skip", "executed": False, "why": "duplicate", "reason": "duplicate"}
    
    order: Optional[OrderDTO] = None
    try:
        if side == "buy":
            if quote_amount is None or quote_amount <= 0:
                return {"action": "skip", "executed": False, "why": "invalid_quote_amount"}
            cid = make_client_order_id(exchange, f"{symbol}:buy:{now_ms()}")
            order = await broker.create_market_buy_quote(symbol=symbol, quote_amount=quote_amount, client_order_id=cid)
            
            # Update position after buy
            if order and order.filled:
                new_position = position_base + order.filled
                storage.positions.set_base_qty(symbol, new_position)
                if hasattr(storage, 'trades') and hasattr(storage.trades, 'add_from_order'):
                    storage.trades.add_from_order(order)
        else:  # sell
            amt = base_amount
            if amt is None:
                amt = position_base
            if not amt or amt <= 0:
                return {"action": "skip", "executed": False, "why": "no_base_to_sell"}
            cid = make_client_order_id(exchange, f"{symbol}:sell:{now_ms()}")
            order = await broker.create_market_sell_base(symbol=symbol, base_amount=amt, client_order_id=cid)
            
            # Update position after sell
            if order and order.filled:
                new_position = position_base - order.filled
                storage.positions.set_base_qty(symbol, new_position)
                if hasattr(storage, 'trades') and hasattr(storage.trades, 'add_from_order'):
                    storage.trades.add_from_order(order)
    except Exception as exc:
        inc("errors_total", kind="execute_trade_failed")
        _log.error("execute_trade_failed", extra={"error": str(exc), "side": side})
        await bus.publish("trade.failed", {"symbol": symbol, "error": str(exc), "side": side}, key=symbol)
        return {"action": "skip", "executed": False, "why": f"place_order_failed:{exc}"}

    if order:
        inc("orders_placed_total", side=(order.side or side))

    # Ensure protective exits after buy
    if protective_exits and side == "buy" and order:
        try:
            await protective_exits.ensure(symbol=symbol)
        except Exception as exc:
            inc("errors_total", kind="exits_ensure_failed")
            _log.error("exits_ensure_failed", extra={"error": str(exc)})

    # Publish completion event
    if order:
        await bus.publish(
            "trade.completed",
            {
                "symbol": symbol,
                "decision": side,
                "action": side,  # Added for compatibility
                "executed": True,
                "order_id": getattr(order, "id", None),
                "amount": str(getattr(order, "amount", "")) if order else "",
                "filled": str(getattr(order, "filled", "")) if order else "",
            },
            key=symbol,
        )
        return {"action": side, "executed": True, "decision": side, "order": order, "order_id": order.id}
    
    # If we're holding position but protective exits are enabled, ensure they're set
    if protective_exits and position_base > 0:
        try:
            await protective_exits.ensure(symbol=symbol)
        except Exception as exc:
            inc("errors_total", kind="exits_ensure_failed")
            _log.error("exits_ensure_failed", extra={"error": str(exc)})
    
    return {"action": "hold", "executed": False, "decision": "hold"}