from __future__ import annotations

import asyncio
from typing import List, Tuple

from crypto_ai_bot.app.compose import build_container_async
from crypto_ai_bot.core.application.symbols import canonical
from crypto_ai_bot.utils.decimal import dec


def _symbols_from_settings(settings) -> List[str]:
    raw = (getattr(settings, "SYMBOLS", "") or "").strip()
    if raw:
        return [canonical(s.strip()) for s in raw.split(",") if s.strip()]
    return [canonical(getattr(settings, "SYMBOL"))]


async def main() -> None:
    c = await build_container_async()
    symbols = _symbols_from_settings(c.settings)
    rows: List[Tuple[str, str, str, str]] = []

    total_realized = dec("0")
    total_turnover = dec("0")

    for sym in symbols:
        realized = c.storage.trades.daily_pnl_quote(sym)
        turnover = c.storage.trades.daily_turnover_quote(sym)
        cnt5 = c.storage.trades.count_orders_last_minutes(sym, 5)
        rows.append((sym, str(realized), str(turnover), str(cnt5)))
        total_realized += realized
        total_turnover += turnover

    w1, w2, w3, w4 = 18, 18, 18, 12
    print(f"{'SYMBOL'.ljust(w1)}{'REALIZED_PNL(Q)'.ljust(w2)}{'TURNOVER(Q)'.ljust(w3)}{'ORDERS_5M'.ljust(w4)}")
    print("-" * (w1 + w2 + w3 + w4))
    for r in rows:
        print(f"{r[0].ljust(w1)}{r[1].ljust(w2)}{r[2].ljust(w3)}{r[3].ljust(w4)}")
    print("-" * (w1 + w2 + w3 + w4))
    print(f"{'TOTAL'.ljust(w1)}{str(total_realized).ljust(w2)}{str(total_turnover).ljust(w3)}{'':ljust(0)}")


if __name__ == "__main__":
    asyncio.run(main())
