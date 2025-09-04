from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from crypto_ai_bot.app.compose import build_container_async
from crypto_ai_bot.core.application.reconciliation import (
    BalancesReconciler,
    OrdersReconciler,
    ReconciliationSuite,
    build_report,
    reconcile_positions,
)


async def _run_reconcile(symbol: str) -> dict[str, Any]:
    c = await build_container_async()

    # Набор сверок (можно добавлять другие IReconciler)
    suite = ReconciliationSuite(
        reconcilers=[
            OrdersReconciler(storage=c.storage, broker=c.broker),
        ]
    )
    discrepancies = await suite.run(symbol=symbol)
    report = build_report(discrepancies=discrepancies)

    # Сверка балансов (oneshot)
    bal = await BalancesReconciler(broker=c.broker, symbol=symbol).run_once()

    # Сверка позиций (обновляет unrealized по последней цене)
    await reconcile_positions(
        symbol=symbol, storage=c.storage, broker=c.broker, bus=c.bus, _settings=c.settings
    )

    # Позиция после сверки
    pos = c.storage.positions.get_position(symbol)
    pos_base = getattr(pos, "base_qty", "0") if pos else "0"

    return {
        "symbol": symbol,
        "orders_report": report,
        "balances": bal,
        "position_base": str(pos_base),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cab-reconcile", description="Reconcile orders/positions/balances")
    p.add_argument("--symbol", help="Override symbol (default from settings)")
    args = p.parse_args(argv)

    async def _get_symbol() -> str:
        c = await build_container_async()
        return args.symbol or c.settings.SYMBOL

    symbol = asyncio.run(_get_symbol())
    result = asyncio.run(_run_reconcile(symbol))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
