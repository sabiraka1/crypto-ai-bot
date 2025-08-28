from __future__ import annotations

import argparse
import asyncio
import json
from typing import Optional

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.core.application.reconciliation.orders import OrdersReconciler  # ← ИСПРАВЛЕНО
from crypto_ai_bot.core.application.reconciliation.balances import BalancesReconciler


async def _run_reconcile(symbol: str) -> dict:
    c = build_container()
    
    # Сверка ордеров
    orders_rec = OrdersReconciler(c.broker, symbol)
    orders = await orders_rec.run_once()
    
    # Сверка балансов  
    balances_rec = BalancesReconciler(c.broker, symbol)
    balances = await balances_rec.run_once()
    
    # Сверка позиций
    pos = c.storage.positions.get_position(symbol)
    
    return {
        "symbol": symbol,
        "orders": orders,
        "balances": balances,
        "position_base": str(pos.base_qty)
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="cab-reconcile", description="Reconcile orders/positions/balances")
    p.add_argument("--symbol", help="Override symbol (default from settings)")
    args = p.parse_args(argv)
    
    c = build_container()
    symbol = args.symbol or c.settings.SYMBOL
    
    result = asyncio.run(_run_reconcile(symbol))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())