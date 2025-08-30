from __future__ import annotations

from typing import List
from crypto_ai_bot.core.application.ports import StoragePort, BrokerPort, EventBusPort
from crypto_ai_bot.core.application.symbols import canonical
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.metrics import inc, observe
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("reconcile.positions")


async def reconcile_positions_batch(
    *, symbols: List[str], storage: StoragePort, broker: BrokerPort, bus: EventBusPort
) -> None:
    """Батч-сверка позиций: один SQL на все символы, по брокеру по символу (ограничение порта)."""
    if not symbols:
        return
    # DB-вызов один раз
    pos_map = storage.positions.get_positions_many(symbols)

    for sym in symbols:
        try:
            t0 = time.time()
            b = await broker.fetch_balance(sym)
            observe("reconcile.fetch_balance.ms", (time.time() - t0) * 1000.0)
            local_base = pos_map[sym].base_qty
            exch_base = dec(str(b["free_base"]))
            if local_base != exch_base:
                await bus.publish("reconcile.position_mismatch", {
                    "symbol": sym,
                    "local": str(local_base),
                    "exchange": str(exch_base),
                })
                _log.warning("position_mismatch", extra={"symbol": sym, "local": str(local_base), "exchange": str(exch_base)})
        except Exception as exc:
            _log.error("reconcile_error", extra={"symbol": sym, "error": str(exc)})
            inc("reconcile.error", {"phase": "positions"})
