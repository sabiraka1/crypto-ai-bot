from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from ...brokers.base import TickerDTO
@dataclass(frozen=True)
class TickerRow:
    symbol: str
    last: Decimal
    bid: Decimal
    ask: Decimal
    ts_ms: int
class MarketDataRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn
    def store_ticker(self, ticker: TickerDTO) -> None:
        self._c.execute(
            """
            INSERT OR REPLACE INTO ticker_snapshots(symbol, last, bid, ask, ts_ms)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ticker.symbol, str(ticker.last), str(ticker.bid), str(ticker.ask), int(ticker.timestamp)),
        )
    def get_last_ticker(self, symbol: str) -> Optional[TickerRow]:
        cur = self._c.execute(
            "SELECT symbol, last, bid, ask, ts_ms FROM ticker_snapshots WHERE symbol=? ORDER BY ts_ms DESC LIMIT 1",
            (symbol,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return TickerRow(
            symbol=row[0], last=Decimal(str(row[1])), bid=Decimal(str(row[2])), ask=Decimal(str(row[3])), ts_ms=int(row[4])
        )