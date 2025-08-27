from __future__ import annotations

from decimal import Decimal
from typing import Optional, Dict, Any

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker, OrderDTO
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.brokers.symbols import parse_symbol
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskInputs  # ← доменная модель
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.ids import make_client_order_id
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("use_cases.eval_and_execute")


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
    fee_estimate_pct: Decimal = Decimal("0.001"),
) -> Optional[OrderDTO]:
    p = parse_symbol(symbol)

    # 1) рыночные данные
    ticker = await broker.fetch_ticker(symbol)
    last = ticker.last or ticker.bid or ticker.ask
    if not last or last <= 0:
        return None

    # 2) построить входы для риск-менеджера (доменная модель)
    orders_last_hour = storage.trades.count_recent_orders(hours=1) if hasattr(storage, "trades") else 0
    pos = storage.positions.get_position(symbol)
    position_base = pos.base_qty or Decimal("0")

    spread_pct = (ticker.ask - ticker.bid) / last if (ticker.ask and ticker.bid and last) else Decimal("0")
    inputs = RiskInputs(
        now_ms=now_ms(),
        action=(force_action or "BUY_QUOTE"),
        spread_pct=spread_pct,
        position_base=position_base,
        orders_last_hour=int(orders_last_hour or 0),
        daily_pnl_quote=storage.audit.daily_pnl_quote() if hasattr(storage, "audit") else Decimal("0"),
        est_fee_pct=fee_estimate_pct,
        est_slippage_pct=Decimal("0"),
    )
    decision = risk_manager.check(inputs)
    if not decision.get("ok", False):
        inc("orders_blocked_total", reason=",".join(decision.get("reasons", [])))
        _log.info("risk_blocked", extra=decision)
        return None

    # 3) идемпотентность (тайм-бакет)
    bucket = (now_ms() // int(idempotency_bucket_ms)) * int(idempotency_bucket_ms)
    client_id = make_client_order_id(exchange, f"{symbol}:{inputs.action}:{bucket}")

    # 4) исполнение
    order: Optional[OrderDTO] = None
    if inputs.action == "BUY_QUOTE":
        order = await broker.create_market_buy_quote(symbol=symbol, quote_amount=fixed_quote_amount, client_order_id=client_id)
    elif inputs.action == "SELL_BASE":
        base_qty = position_base
        if base_qty > 0:
            order = await broker.create_market_sell_base(symbol=symbol, base_amount=base_qty, client_order_id=client_id)

    if order:
        storage.audit.log_order(order) if hasattr(storage, "audit") else None
        storage.positions.update_from_trade({"symbol": symbol, "side": order.side, "amount": order.amount}) if hasattr(storage, "positions") else None
        inc("orders_placed_total", side=order.side)
        await bus.publish("orders.executed", {"symbol": symbol, "side": order.side, "client_order_id": order.client_order_id}, key=symbol)

    # 5) защитные выходы (если открыта позиция)
    try:
        await protective_exits.ensure(symbol=symbol)
    except Exception as exc:
        _log.error("exits.ensure_failed", extra={"error": str(exc)})

    return order
