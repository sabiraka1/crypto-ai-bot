from __future__ import annotations

from decimal import Decimal
from typing import Optional

from ...utils.decimal import dec
from ...utils.time import now_ms
from ...utils.ids import make_client_order_id
from ...utils.logging import get_logger
from ...utils.exceptions import TransientError, ValidationError
from ...infrastructure.brokers.base import IBroker
from ...infrastructure.events.bus import AsyncEventBus
from ...infrastructure.storage.facade import Storage
from ...infrastructure.brokers.symbols import parse_symbol
from ...domain.risk.manager import RiskManager, RiskInputs

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
    protective_exits,                     # тот же тип, что в твоём коде
    fee_estimate_pct: Decimal,            # ОЦЕНКА комиссии
) -> None:
    # 1) рынок
    t = await broker.fetch_ticker(symbol)
    last = t.last if t.last > 0 else t.ask
    spread = (t.ask - t.bid) if (t.ask and t.bid) else Decimal("0")
    spread_pct = (spread / last) if last > 0 else Decimal("0")

    # 2) состояние
    pos = storage.positions.get_position(symbol)
    position_base = pos.base_qty or Decimal("0")

    # 3) метрики частоты/PNL
    orders_last_hour = storage.trades.count_orders_last_minutes(symbol, 60) if hasattr(storage.trades, "count_orders_last_minutes") else 0
    daily_pnl_quote = storage.trades.daily_pnl_quote(symbol) if hasattr(storage.trades, "daily_pnl_quote") else Decimal("0")

    # 4) оценки
    est_fee_pct = dec(getattr(broker, "fee_rate", fee_estimate_pct))
    est_slippage_pct = spread_pct / Decimal("2")

    # 5) действие (или твоя стратегия)
    action = force_action or "BUY_QUOTE"

    # 6) риск
    r = risk_manager.check(
        RiskInputs(
            now_ms=now_ms(),
            action=action,
            spread_pct=spread_pct,
            position_base=position_base,
            orders_last_hour=orders_last_hour,
            daily_pnl_quote=daily_pnl_quote,
            est_fee_pct=est_fee_pct,
            est_slippage_pct=est_slippage_pct,
        )
    )
    if not r["ok"]:
        _log.info("trade_blocked", extra={"reasons": r["reasons"]})
        await bus.publish("trade.blocked", {"symbol": symbol, "reasons": r["reasons"]}, key=symbol)
        return

    # 7) исполнение
    client_id = make_client_order_id(exchange, f"{symbol}:{action.lower()}")
    if action == "BUY_QUOTE":
        order = await broker.create_market_buy_quote(symbol=symbol, quote_amount=fixed_quote_amount, client_order_id=client_id)
    else:
        if position_base <= 0:
            _log.info("sell_skipped_empty", extra={"symbol": symbol})
            return
        order = await broker.create_market_sell_base(symbol=symbol, base_amount=position_base, client_order_id=client_id)

    risk_manager.on_trade_executed(order.timestamp or now_ms())
    await bus.publish("trade.completed", {"symbol": symbol, "side": order.side, "amount": str(order.amount)}, key=symbol)
    await protective_exits.ensure(symbol=symbol)
