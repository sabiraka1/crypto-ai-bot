# src/crypto_ai_bot/core/storage/repositories/trades.py
from __future__ import annotations
import json
from decimal import Decimal
from typing import Any, Dict, List
import sqlite3

from crypto_ai_bot.core.storage.interfaces import Trade, TradeRepository


class SqliteTradeRepository(TradeRepository):  # type: ignore[misc]
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    def insert(self, trade: Trade) -> None:
        self._con.execute(
            """
            INSERT OR REPLACE INTO trades
            (id, symbol, side, amount, price, cost, fee_currency, fee_cost, ts, client_order_id, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.id,
                trade.symbol,
                trade.side,
                str(trade.amount),
                str(trade.price),
                str(trade.cost),
                trade.fee_currency,
                str(trade.fee_cost),
                int(trade.ts),
                trade.client_order_id,
                json.dumps(trade.meta or {}, ensure_ascii=False, separators=(",", ":")),
            ),
        )

    def list_by_symbol(self, symbol: str, limit: int = 100) -> List[Trade]:
        cur = self._con.execute(
            "SELECT * FROM trades WHERE symbol = ? ORDER BY ts DESC LIMIT ?;",
            (symbol, int(limit)),
        )
        out: List[Trade] = []
        for r in cur.fetchall():
            out.append(
                Trade(
                    id=str(r["id"]),
                    symbol=str(r["symbol"]),
                    side=str(r["side"]),
                    amount=Decimal(str(r["amount"])),
                    price=Decimal(str(r["price"])),
                    cost=Decimal(str(r["cost"])),
                    fee_currency=str(r["fee_currency"]),
                    fee_cost=Decimal(str(r["fee_cost"])),
                    ts=int(r["ts"]),
                    client_order_id=r["client_order_id"],
                    meta=json.loads(r["meta_json"] or "{}"),
                )
            )
        return out
