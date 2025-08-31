from __future__ import annotations

from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.application.ports import StoragePort, BrokerPort, EventBusPort
from crypto_ai_bot.core.application.use_cases.place_order import place_order, PlaceOrderInputs, PlaceOrderResult
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("application.protective_exits")


async def maybe_exit(*, symbol: str, storage: StoragePort, broker: BrokerPort, bus: EventBusPort, settings: Any) -> None:
    """
    Простой и безопасный protective exit:
    - Если позиция по символу > 0:
      - Если PROFIT >= EXIT_TAKE_PROFIT_PCT → продаём MIN_SELL_BASE (или всю позицию, если меньше минимума)
      - Если LOSS   <= -EXIT_STOP_LOSS_PCT → продаём MIN_SELL_BASE (аналогично)
    """
    pos = storage.positions.get_position(symbol)
    if not pos or (pos.base_qty or dec("0")) <= 0:
        return

    base_qty = pos.base_qty
    last_price = getattr(pos, "last_price", None)
    if not last_price or last_price <= 0:
        # попробуем взять цену у брокера
        try:
            t = await broker.fetch_ticker(symbol)
            last_price = dec(str(t.get("last") or t.get("bid") or t.get("ask") or "0"))
        except Exception:
            return
        if last_price <= 0:
            return

    avg = pos.avg_entry_price or dec("0")
    if avg <= 0:
        return

    change_pct = ((last_price - avg) / avg) * 100

    tp = dec(str(getattr(settings, "EXIT_TAKE_PROFIT_PCT", 0) or 0))
    sl = dec(str(getattr(settings, "EXIT_STOP_LOSS_PCT", 0) or 0))
    min_sell = dec(str(getattr(settings, "EXIT_MIN_SELL_BASE", 0) or 0))

    need_sell = dec("0")
    reason = ""

    if tp > 0 and change_pct >= tp:
        need_sell = min(min_sell if min_sell > 0 else base_qty, base_qty)
        reason = "take_profit"
    elif sl > 0 and change_pct <= -sl:
        need_sell = min(min_sell if min_sell > 0 else base_qty, base_qty)
        reason = "stop_loss"

    if need_sell <= 0:
        return

    # разместить рыночный sell через единый use-case
    res: PlaceOrderResult = await place_order(
        storage=storage,
        broker=broker,
        bus=bus,
        settings=settings,
        inputs=PlaceOrderInputs(symbol=symbol, side="sell", base_amount=need_sell),
    )
    if res.ok:
        inc("protective_exits.sell", {"reason": reason})
        await bus.publish("protective.exit", {"symbol": symbol, "reason": reason, "amount": str(need_sell)})
    else:
        _log.warning("protective_exit_failed", extra={"symbol": symbol, "reason": reason, "error": res.reason})


# Совместимость со старым compose: могли передавать объект c .run()
async def run(*, symbol: str, storage: StoragePort, broker: BrokerPort, bus: EventBusPort, settings: Any) -> None:
    await maybe_exit(symbol=symbol, storage=storage, broker=broker, bus=bus, settings=settings)
