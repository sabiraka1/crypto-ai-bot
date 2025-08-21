from __future__ import annotations
import sqlite3
from typing import List

from crypto_ai_bot.core.storage.repositories import ensure_schema


class MarketDataRepositoryImpl:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        ensure_schema(self.conn)

    def save_snapshot(self, symbol: str, ohlcv: list[list[float]]) -> None:
        # ohlcv: [[ts, o,h,l,c,v], ...]
        if not ohlcv:
            return
        rows = []
        for ts, o, h, l, c, v in ohlcv:
            rows.append((symbol, int(ts), float(o), float(h), float(l), float(c), float(v)))
        self.conn.executemany(
            """
            INSERT INTO ohlcv(symbol, ts_ms, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, ts_ms) DO UPDATE SET
              open=excluded.open,
              high=excluded.high,
              low=excluded.low,
              close=excluded.close,
              volume=excluded.volume;
            """,
            rows,
        )
        self.conn.commit()

    def get_latest_ohlcv(self, symbol: str, *, limit: int = 100) -> list[list[float]]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT ts_ms, open, high, low, close, volume FROM ohlcv WHERE symbol=? ORDER BY ts_ms DESC LIMIT ?",
            (symbol, int(limit)),
        )
        rows = cur.fetchall()
        cur.close()
        # Возвращаем в обратном порядке (от старого к новому)
        rows.reverse()
        return [list(map(float, r)) for r in rows]
