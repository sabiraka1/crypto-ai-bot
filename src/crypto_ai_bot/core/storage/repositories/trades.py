from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from .base import _WriteCountingRepo

class TradeRepository(_WriteCountingRepo):
    """
    Ожидаем схему (миграции):
      trades(id INTEGER PK, ts INTEGER, symbol TEXT, side TEXT, price REAL, amount REAL, fee REAL, pnl REAL)
      индексы по (symbol, ts)
    """

    def insert(self, trade: Dict[str, Any]) -> None:
        ts = int(trade.get("ts") or datetime.now(tz=timezone.utc).timestamp())
        symbol = str(trade.get("symbol"))
        side = str(trade.get("side"))
        price = float(trade.get("price", 0.0))
        amount = float(trade.get("amount", 0.0))
        fee = float(trade.get("fee", 0.0))
        pnl = float(trade.get("pnl", 0.0))

        cur = self._con.cursor()
        try:
            cur.execute(
                "INSERT INTO trades(ts, symbol, side, price, amount, fee, pnl) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, symbol, side, price, amount, fee, pnl),
            )
            self._inc_writes("trades", 1)
        finally:
            cur.close()

    def list_by_symbol(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        cur = self._con.cursor()
        try:
            cur.execute("SELECT id, ts, symbol, side, price, amount, fee, pnl FROM trades WHERE symbol=? ORDER BY ts DESC LIMIT ?", (symbol, int(limit)))
            rows = cur.fetchall()
            return [
                {"id": r[0], "ts": r[1], "symbol": r[2], "side": r[3], "price": r[4], "amount": r[5], "fee": r[6], "pnl": r[7]}
                for r in rows
            ]
        finally:
            cur.close()

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        cur = self._con.cursor()
        try:
            cur.execute("SELECT id, ts, symbol, side, price, amount, fee, pnl FROM trades ORDER BY ts DESC LIMIT ?", (int(limit),))
            rows = cur.fetchall()
            return [
                {"id": r[0], "ts": r[1], "symbol": r[2], "side": r[3], "price": r[4], "amount": r[5], "fee": r[6], "pnl": r[7]}
                for r in rows
            ]
        finally:
            cur.close()
