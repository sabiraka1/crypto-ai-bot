from __future__ import annotations

import sqlite3
from typing import Any

from ...brokers.base import TickerDTO


class MarketDataRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS market_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                last TEXT,
                bid TEXT,
                ask TEXT,
                ts_ms INTEGER NOT NULL
            )
            """
        )
        self._c.execute("CREATE INDEX IF NOT EXISTS idx_md_symbol_ts ON market_data(symbol, ts_ms)")
        self._c.commit()

    def store_ticker(self, ticker: TickerDTO) -> None:
        self._c.execute(
            "INSERT INTO market_data(symbol, last, bid, ask, ts_ms) VALUES(?,?,?,?,?)",
            (ticker.symbol, str(ticker.last), str(ticker.bid), str(ticker.ask), ticker.timestamp),
        )
        self._c.commit()

    def list_recent(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._c.execute(
            """
            SELECT symbol,last,bid,ask,ts_ms
            FROM market_data
            WHERE symbol=?
            ORDER BY ts_ms DESC
            LIMIT ?
            """,
            (symbol, int(limit)),
        )
        return [dict(r) for r in cur.fetchall()]
