from __future__ import annotations

from decimal import Decimal
from typing import Optional, Dict, Any

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.brokers.symbols import parse_symbol
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskInputs
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits


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
    force_action: Optional[str],
    risk_manager: RiskManager,
    protective_exits: ProtectiveExits,
) -> Dict[str, Any]:
    # 1) рыночные данные
    t = await broker.fetch_ticker(symbol)
    mid = (t.bid + t.ask) / Decimal("2") if t.bid and t.ask else (t.last or Decimal("0"))
    spread_pct = (t.ask - t.bid) / mid if t.bid and t.ask and mid > 0 else Decimal("0")

    # 2) состояние
    pos = storage.positions.get_position(symbol)
    position_base = pos.base_qty or Decimal("0")
    recent_orders = storage.orders.count_recent(hours=1) if hasattr(storage, "orders") else 0
    pnl_daily = storage.pnl.get_today_quote() if hasattr(storage, "pnl") else Decimal("0")
    cooldown_active = storage.cooldown.is_active(symbol) if hasattr(storage, "cooldown") else False

    # 3) риск-чек
    risk = await risk_manager.check(
        RiskInputs(
            spread_pct=spread_pct,
            position_base=position_base,
            recent_orders=recent_orders,
            pnl_daily_quote=pnl_daily,
            cooldown_active=cooldown_active,
        )
    )
    if not risk["ok"] and not force_action:
        return {"action": "skip", "reasons": risk["deny_reasons"]}

    # 4) простейшая логика (пример): если нет позиции — покупаем на фиксированную квоту
    if (position_base <= 0 and fixed_quote_amount > 0) or (force_action == "buy"):
        coid = storage.idempotency.next_client_order_id(exchange, f"{symbol}:buy", bucket_ms=idempotency_bucket_ms)
        order = await broker.create_market_buy_quote(symbol=symbol, quote_amount=fixed_quote_amount, client_order_id=coid)
        storage.orders.save_market_buy(symbol=symbol, order=order, idempotency_key=coid, ttl_sec=idempotency_ttl_sec)
        await bus.publish("trade.executed", {"symbol": symbol, "side": "buy", "amount": str(order.amount)}, key=symbol)
        return {"action": "buy", "order_id": order.id}

    # 5) защитные выходы если позиция > 0
    if position_base > 0:
        await protective_exits.ensure(symbol=symbol)

    return {"action": "hold"}
