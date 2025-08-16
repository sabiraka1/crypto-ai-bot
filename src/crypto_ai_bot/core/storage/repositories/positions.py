# src/crypto_ai_bot/core/storage/repositories/positions.py
from __future__ import annotations
from typing import Any, Dict, Optional
import sqlite3

from crypto_ai_bot.core.storage.interfaces import PositionRepository


class SqlitePositionRepository(PositionRepository):  # type: ignore[misc]
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    def get_open_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        cur = self._con.execute("SELECT * FROM positions WHERE symbol = ?;", (symbol,))
        r = cur.fetchone()
        return dict(r) if r else None

    def upsert(self, position: Dict[str, Any]) -> None:
        self._con.execute(
            """
            INSERT INTO positions(symbol, size, avg_price, updated_ts)
            VALUES(:symbol, :size, :avg_price, :updated_ts)
            ON CONFLICT(symbol) DO UPDATE SET
                size=excluded.size,
                avg_price=excluded.avg_price,
                updated_ts=excluded.updated_ts
            """,
            position,
        )
