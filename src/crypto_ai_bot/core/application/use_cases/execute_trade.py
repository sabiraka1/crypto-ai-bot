from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.core.domain.risk.manager import RiskInputs, RiskManager
from crypto_ai_bot.core.infrastructure.brokers.base import IBroker, OrderDTO
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.ids import make_client_order_id
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.utils.time import now_ms

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
    settings: Any,                      # ← добавлено: прокидываем настройки
    force_action: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute trade with risk management and protective exits.
    """
    side = (side or "").lower()

    # ── Market data (для risk)
    ticker = await broker.fetch_ticker(symbol)
    mid_price = (ticker.bid + ticker.ask) / Decimal("2") if ticker.bid and ticker.ask else (ticker.last or Decimal("0"))
    spread_frac = ((ticker.ask - ticker.bid) / mid_price) if ticker.bid and ticker.ask and mid_price > 0 else Decimal("0")

    # ── Состояние
    pos = storage.positions.get_position(symbol)
    position_base = pos.base_qty if pos else Decimal("0")

    # ── История/ограничители (если реализованы в storage)
    recent_orders = storage.trades.count_orders_last_minutes(symbol, 60) if getattr(storage, "trades", None) and hasattr(storage.trades, "count_orders_last_minutes") else 0
    pnl_daily = storage.trades.daily_pnl_quote(symbol) if getattr(storage, "trades", None) and hasattr(storage.trades, "daily_pnl_quote") else Decimal("0")
    cooldown_active = storage.cooldowns.is_active(symbol) if getattr(storage, "cooldowns", None) and hasattr(storage.cooldowns, "is_active") else False

    # ── Risk check (SYNC!) — теперь прокидываем оценки комиссии/проскальзывания
    if risk_manager and not force_action:
        fee_est = dec(str(getattr(settings, "FEE_PCT_ESTIMATE", "0")))          # например 0.001
        slip_est = spread_frac                                                  # оценка проскальзывания по текущему спреду

        r_inputs = RiskInputs(
            spread_pct=spread_frac,
            position_base=position_base,
            recent_orders=recent_orders,
            pnl_daily_quote=pnl_daily,
            cooldown_active=cooldown_active,
            est_fee_pct=fee_est,
            est_slippage_pct=slip_est,
        )
        risk_result = risk_manager.check(r_inputs)  # ← без await (check синхронный)
        if isinstance(risk_result, dict) and not risk_result.get("ok", True):
            reasons = risk_result.get("deny_reasons", risk_result.get("reasons", ["unspecified"]))
            reason_str = ";".join(reasons) if isinstance(reasons, list) else str(reasons)
            inc("orders_blocked_total", reason=reason_str)
            await bus.publish("trade.blocked", {"symbol": symbol, "reason": reason_str, "side": side}, key=symbol)
            return {"action": "skip", "executed": False, "reasons": reasons, "why": f"blocked:{reason_str}"}

    # ── Определяем действие, если side не задан
    if side not in ("buy", "sell"):
        side = "buy" if position_base <= 0 else "sell"

    # ── Идемпотентность только для buy
    if side == "buy":
        bucket = (now_ms() // idempotency_bucket_ms) * idempotency_bucket_ms
        idem_key = f"{symbol}:buy:{bucket}"
        if getattr(storage, "idempotency", None) and hasattr(storage.idempotency, "check_and_store"):
            if not storage.idempotency.check_and_store(idem_key, ttl_sec=idempotency_ttl_sec, default_bucket_ms=idempotency_bucket_ms):
                return {"action": "skip", "executed": False, "why": "duplicate", "reason": "duplicate"}

    # ── Нормализуем входные суммы к Decimal (на случай float из Settings)
    q_amt = dec(str(quote_amount)) if quote_amount is not None else None
    b_amt = dec(str(base_amount)) if base_amount is not None else None

    order: Optional[OrderDTO] = None
    try:
        if side == "buy":
            if q_amt is None or q_amt <= 0:
                return {"action": "skip", "executed": False, "why": "invalid_quote_amount"}
            cid = make_client_order_id(exchange, f"{symbol}:buy:{now_ms()}")
            order = await broker.create_market_buy_quote(symbol=symbol, quote_amount=q_amt, client_order_id=cid)
            if order and order.filled:
                storage.positions.set_base_qty(symbol, position_base + order.filled)
                if getattr(storage, "trades", None) and hasattr(storage.trades, "add_from_order"):
                    storage.trades.add_from_order(order)
        else:  # sell
            amt = b_amt if b_amt is not None else position_base
            if not amt or amt <= 0:
                return {"action": "skip", "executed": False, "why": "no_base_to_sell"}
            cid = make_client_order_id(exchange, f"{symbol}:sell:{now_ms()}")
            order = await broker.create_market_sell_base(symbol=symbol, base_amount=amt, client_order_id=cid)
            if order and order.filled:
                storage.positions.set_base_qty(symbol, position_base - order.filled)
                if getattr(storage, "trades", None) and hasattr(storage.trades, "add_from_order"):
                    storage.trades.add_from_order(order)
    except Exception as exc:
        inc("errors_total", kind="execute_trade_failed")
        _log.error("execute_trade_failed", extra={"error": str(exc), "side": side})
        await bus.publish("trade.failed", {"symbol": symbol, "error": str(exc), "side": side}, key=symbol)
        return {"action": "skip", "executed": False, "why": f"place_order_failed:{exc}"}

    if order:
        inc("orders_placed_total", side=(order.side or side))
        # защитные выходы после покупки
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
                "action": side,
                "executed": True,
                "order_id": getattr(order, "id", None),
                "amount": str(getattr(order, "amount", "")) if order else "",
                "filled": str(getattr(order, "filled", "")) if order else "",
            },
            key=symbol,
        )
        return {"action": side, "executed": True, "decision": side, "order": order, "order_id": order.id}

    # если держим позицию — актуализируем защитные выходы
    if protective_exits and position_base > 0:
        try:
            await protective_exits.ensure(symbol=symbol)
        except Exception as exc:
            inc("errors_total", kind="exits_ensure_failed")
            _log.error("exits_ensure_failed", extra={"error": str(exc)})

    return {"action": "hold", "executed": False, "decision": "hold"}
