from __future__ import annotations

from decimal import Decimal
from typing import Optional, Dict, Any

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.ids import make_client_order_id
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.exceptions import TransientError, ValidationError
from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.core.infrastructure.brokers.base import IBroker, OrderDTO
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.brokers.symbols import parse_symbol
from ..risk.manager import RiskManager
from ..risk.protective_exits import ProtectiveExits
from ..strategies.manager import StrategyManager

_log = get_logger("usecase.eval")


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
    fee_estimate_pct: Decimal = dec("0.001"),  # 0.1% default fee estimate
) -> Dict[str, Any]:
    inc("orc_eval_ticks_total")
    
    # 1) рыночные данные
    t = await broker.fetch_ticker(symbol)
    last = t.last if t.last and t.last > 0 else t.ask
    spread = (t.ask - t.bid) if (t.ask and t.bid) else dec("0")
    spread_pct = (spread / last) if last and last > 0 else dec("0")

    # 2) состояние позиции
    pos = storage.positions.get_position(symbol)
    position_base = pos.base_qty or dec("0")

    # 3) метрики частоты/PNL (заглушки для совместимости)
    orders_last_hour = getattr(storage.trades, "count_orders_last_minutes", lambda *args: 0)(symbol, 60)
    daily_pnl_quote = getattr(storage.trades, "daily_pnl_quote", lambda *args: dec("0"))(symbol)

    # 4) оценки комиссии/проскальзывания
    est_fee_pct = dec(getattr(broker, "fee_rate", fee_estimate_pct))
    est_slippage_pct = spread_pct / dec("2")

    # 5) определение действия
    if force_action:
        action = force_action.upper()
    else:
        # стратегия (упрощенная версия для совместимости)
        ctx = {"ticker": {"last": last, "bid": t.bid, "ask": t.ask}, "spread": float(spread_pct * 100)}
        manager = StrategyManager()
        decision, explain = manager.decide(symbol=symbol, exchange=exchange, context=ctx, mode="first")
        action = "BUY_QUOTE" if decision == "buy" else "SELL_BASE" if decision == "sell" else "HOLD"

    # 6) риск-проверка
    if risk_manager:
        # Подготавливаем входы для риск-менеджера
        risk_inputs = {
            "now_ms": now_ms(),
            "action": action,
            "spread_pct": spread_pct,
            "position_base": position_base,
            "orders_last_hour": orders_last_hour,
            "daily_pnl_quote": daily_pnl_quote,
            "est_fee_pct": est_fee_pct,
            "est_slippage_pct": est_slippage_pct,
        }
        
        raw = await risk_manager.check(symbol=symbol, action=action.lower(), evaluation=risk_inputs)
        
        # нормализация результата риска
        if isinstance(raw, dict):
            ok = raw.get("ok", True)
            reasons = raw.get("reasons", [])
            if isinstance(reasons, list):
                reason_str = ";".join(map(str, reasons))
            else:
                reason_str = str(raw.get("reason", ""))
        else:
            ok, reason_str = (True, "") if raw is None else (bool(raw), "unspecified")
            
        if not ok:
            inc("orders_blocked_total", reason=(reason_str or "unspecified"))
            await bus.publish("trade.blocked", {"symbol": symbol, "reason": reason_str}, key=symbol)
            return {"executed": False, "why": f"blocked:{reason_str}"}

    # 7) исполнение ордера
    order: Optional[OrderDTO] = None
    try:
        if action == "BUY_QUOTE" or action.lower() == "buy":
            client_id = make_client_order_id(exchange, f"{symbol}:buy:{now_ms()}")
            order = await broker.create_market_buy_quote(
                symbol=symbol, 
                quote_amount=fixed_quote_amount, 
                client_order_id=client_id
            )
        elif action == "SELL_BASE" or action.lower() == "sell":
            if position_base <= 0:
                _log.info("sell_skipped_empty", extra={"symbol": symbol})
                return {"executed": False, "why": "no_position_to_sell"}
            
            client_id = make_client_order_id(exchange, f"{symbol}:sell:{now_ms()}")
            order = await broker.create_market_sell_base(
                symbol=symbol, 
                base_amount=position_base, 
                client_order_id=client_id
            )
        else:
            # HOLD или неизвестное действие
            return {"executed": False, "why": "hold_or_unknown_action"}
            
    except Exception as exc:
        inc("errors_total", kind="place_order_failed")
        _log.error("place_order_failed", extra={"error": str(exc)})
        await bus.publish("trade.failed", {"symbol": symbol, "error": str(exc)}, key=symbol)
        return {"executed": False, "why": f"place_order_failed:{exc}"}

    # 8) пост-обработка
    if order:
        inc("orders_placed_total", side=(order.side or "na"))
        
        # уведомляем риск-менеджер об исполнении
        if risk_manager and hasattr(risk_manager, "on_trade_executed"):
            try:
                risk_manager.on_trade_executed(order.timestamp or now_ms())
            except Exception:
                pass

    # 9) защитные выходы
    if protective_exits and order and order.side == "buy":
        try:
            await protective_exits.ensure(symbol=symbol)
        except Exception as exc:
            inc("errors_total", kind="exits_ensure_failed")
            _log.error("exits_ensure_failed", extra={"error": str(exc)})

    # 10) финальное событие
    await bus.publish(
        "trade.completed",
        {
            "symbol": symbol,
            "decision": action,
            "executed": bool(order),
            "order_id": getattr(order, "id", None),
            "amount": str(getattr(order, "amount", "")) if order else "",
            "filled": str(getattr(order, "filled", "")) if order else "",
        },
        key=symbol,
    )

    return {"executed": bool(order), "decision": action, "order": order}