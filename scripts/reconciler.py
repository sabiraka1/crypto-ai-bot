#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from src.crypto_ai_bot.core.reconciliation.orders import OrdersReconciler
from src.crypto_ai_bot.core.reconciliation.positions import PositionsReconciler
from src.crypto_ai_bot.core.reconciliation.balances import BalancesReconciler
from src.crypto_ai_bot.core.brokers.paper import PaperBroker
from src.crypto_ai_bot.core.storage.facade import Storage


async def main(symbol: str, db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    storage = Storage.from_connection(conn)
    broker = PaperBroker(symbol=symbol, balances={"USDT": 10000})
    o = OrdersReconciler(broker, symbol)
    p = PositionsReconciler(storage=storage, broker=broker, symbol=symbol)
    b = BalancesReconciler(broker, symbol)
    print(await o.run_once())
    print(await p.run_once())
    print(await b.run_once())


if __name__ == "__main__":
    asyncio.run(main("BTC/USDT", "./crypto-ai-bot.db"))