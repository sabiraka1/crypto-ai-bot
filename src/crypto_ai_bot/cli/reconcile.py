from __future__ import annotations

import asyncio
import json
from typing import Optional, Dict, Any

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.core.reconciliation.orders import OrdersReconciler
from crypto_ai_bot.core.reconciliation.positions import PositionsReconciler
from crypto_ai_bot.core.reconciliation.balances import BalancesReconciler


async def _run() -> int:
    c = build_container()
    sym = c.settings.SYMBOL
    orders = OrdersReconciler(c.broker, sym)
    positions = PositionsReconciler(storage=c.storage, broker=c.broker, symbol=sym)
    balances = BalancesReconciler(c.broker, sym)

    rep = {
        "orders": await orders.run_once(),
        "positions": await positions.run_once(),
        "balances": await balances.run_once(),
    }
    print(json.dumps(rep, ensure_ascii=False))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
