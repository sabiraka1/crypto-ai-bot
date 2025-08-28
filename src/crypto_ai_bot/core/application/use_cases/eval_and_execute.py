from __future__ import annotations

from decimal import Decimal
from typing import Optional, Dict, Any

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.ids import make_client_order_id
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.brokers.symbols import parse_symbol
from crypto_ai_bot.core.domain.risk.manager import RiskManager

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
    risk_manager: RiskManager,
    protective_exits,
    fee_estimate_pct: Decimal,
) -> Dict[str, Any]:
    # 1) Рыночные данные
    t = await broker.fetch_ticker(symbol)
    mid = (t.bid + t.ask) / dec("2") if t.bid and t.ask else (t.last or dec("0"))
    spread_pct = ((t.ask - t.bid) / mid * dec("100")) if t.bid and t.ask and mid > 0 else dec("0")

    # 2) Состояние позиции
    pos = storage.positions.get_position(symbol)
    position_base = pos.base_qty or dec("0")

    # 3) Риск-чек (упрощённо)
    risk_inputs = {
        "spread_pct": spread_pct,
        "position_base": position_base,
        "recent_orders": 0,
        "pnl_daily_quote": dec("0"),
        "cooldown_active": False
    }
    risk_check = risk_manager.check(risk_inputs)
    if not risk_check.get("ok", True) and not force_action:
        _log.info("trade_blocked", extra={"reasons": risk_check.get("deny_reasons", [])})
        return {"action": "skip", "reasons": risk_check.get("deny_reasons", [])}

    # 4) Buy, если плоские
    if position_base <= 0 or force_action == "buy":
        bucket = (now_ms() // idempotency_bucket_ms) * idempotency_bucket_ms
        idem_key = f"{symbol}:buy:{bucket}"
        if not storage.idempotency.check_and_store(key=idem_key, ttl_sec=idempotency_ttl_sec, default_bucket_ms=idempotency_bucket_ms):
            return {"action": "skip", "reason": "duplicate"}

        coid = make_client_order_id(exchange, f"{symbol}:buy")
        order = await broker.create_market_buy_quote(
            symbol=symbol,
            quote_amount=fixed_quote_amount,
            client_order_id=coid
        )

        storage.positions.set_base_qty(symbol, position_base + order.filled)
        storage.trades.add_from_order(order)

        await bus.publish("trade.executed", {
            "symbol": symbol,
            "side": "buy",
            "amount": str(order.filled),
            "cost": str(order.cost or (order.filled * order.price if order.price else 0))
        }, key=symbol)

        if protective_exits:
            await protective_exits.ensure(symbol=symbol)

        return {"action": "buy", "order_id": order.id}

    # 5) Если есть позиция — проверяем защитные выходы
    if position_base > 0 and protective_exits:
        await protective_exits.ensure(symbol=symbol)

    return {"action": "hold"}
