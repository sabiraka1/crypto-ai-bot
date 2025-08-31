from __future__ import annotations

import time
from decimal import Decimal
from typing import List

from crypto_ai_bot.core.application.ports import StoragePort, BrokerPort, EventBusPort
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("application.reconcile.positions")


async def reconcile_positions_batch(*, symbols: List[str], storage: StoragePort, broker: BrokerPort, bus: EventBusPort) -> None:
    """
    Простая сверка: подтягиваем текущую цену и обновляем нереализованный PnL.
    """
    for sym in symbols:
        try:
            t = await broker.fetch_ticker(sym)
            last = dec(str(t.get("last") or t.get("bid") or t.get("ask") or "0"))
            if last <= 0:
                continue
            pos = storage.positions.get_position(sym)
            if not pos:
                continue
            base = pos.base_qty or dec("0")
            if base <= 0:
                continue
            avg = pos.avg_entry_price or dec("0")
            if avg <= 0:
                continue
            unreal = (last - avg) * base
            # оптимистичное обновление
            storage.positions.apply_trade(
                symbol=sym, side="buy", base_amount=dec("0"), price=last, fee_quote=dec("0"), last_price=last
            )
            _log.debug("reconcile_ok", extra={"symbol": sym, "unrealized": str(unreal)})
        except Exception as exc:
            _log.warning("reconcile_error", extra={"symbol": sym, "error": str(exc)})
