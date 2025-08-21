from __future__ import annotations
import sqlite3
from typing import Iterable, Any


class PositionsRepositoryImpl:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_open_positions(self) -> Iterable[dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT symbol,
                   SUM(amount) AS base_qty,
                   CASE WHEN SUM(CASE WHEN amount>0 THEN amount*price ELSE 0 END) > 0
                        THEN (SUM(CASE WHEN amount>0 THEN amount*price ELSE 0 END)
                              / NULLIF(SUM(CASE WHEN amount>0 THEN amount ELSE 0 END), 0))
                        ELSE 0 END AS avg_buy_price
            FROM trades
            WHERE status='closed'
            GROUP BY symbol
            HAVING ABS(SUM(amount)) > 1e-12;
            """
        )
        rows = cur.fetchall()
        cur.close()
        return [
            {"symbol": r[0], "base_qty": float(r[1]), "avg_buy_price": float(r[2] or 0.0)}
            for r in rows
        ]

    def has_long(self, symbol: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM trades WHERE symbol=? AND status='closed'", (symbol,))
        qty = cur.fetchone()[0] or 0.0
        cur.close()
        return float(qty) > 1e-12

    def recompute_from_trades(self) -> None:
        # Позиции выводятся агрегатами из trades — явная таблица не ведётся, поэтому действий не требуется
        return None
