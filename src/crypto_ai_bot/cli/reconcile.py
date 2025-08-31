from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from crypto_ai_bot.app.compose import build_container_async  # исправлен импорт
from crypto_ai_bot.core.application.reconciliation.balances import BalancesReconciler
from crypto_ai_bot.core.application.reconciliation.orders import OrdersReconciler


async def _run_reconcile(symbol: str) -> dict[str, Any]:
    c = await build_container_async()  # исправлено на async версию

    # Сверка ордеров
    orders_rec = OrdersReconciler(c.broker, symbol)
    await orders_rec.run_once()  # run_once возвращает None, не присваиваем
    orders = {}  # заглушка, так как run_once не возвращает значение

    # Сверка балансов
    balances_rec = BalancesReconciler(c.broker, symbol)
    await balances_rec.run_once()  # run_once возвращает None
    balances = {}  # заглушка

    # Сверка позиций
    pos = c.storage.positions.get_position(symbol)

    return {
        "symbol": symbol,
        "orders": orders,
        "balances": balances,
        "position_base": str(pos.base_qty)
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cab-reconcile", description="Reconcile orders/positions/balances")
    p.add_argument("--symbol", help="Override symbol (default from settings)")
    args = p.parse_args(argv)

    # Создаем контейнер асинхронно для получения символа
    async def _get_symbol() -> str:
        c = await build_container_async()
        return args.symbol or c.settings.SYMBOL
    
    symbol = asyncio.run(_get_symbol())
    result = asyncio.run(_run_reconcile(symbol))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())