from __future__ import annotations

import argparse
import json
from decimal import Decimal
from typing import Optional

from crypto_ai_bot.app.compose import build_container


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="cab-perf", description="Performance report")
    p.add_argument("--symbol", help="Override symbol (default from settings)")
    args = p.parse_args(argv)

    c = build_container()
    symbol = args.symbol or c.settings.SYMBOL
    trades = c.storage.trades.list_today(symbol)

    realized = Decimal("0")
    buys = sells = 0
    for t in trades:
        side = str(t.get("side") or "").lower()
        cost = Decimal(str(t.get("cost") or "0"))
        if side == "buy":
            realized -= cost
            buys += 1
        elif side == "sell":
            realized += cost
            sells += 1

    out = {
        "symbol": symbol,
        "total_trades": len(trades),
        "buys": buys,
        "sells": sells,
        "realized_quote": str(realized),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
