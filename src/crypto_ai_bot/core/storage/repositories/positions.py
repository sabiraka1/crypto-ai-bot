from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from .base import _WriteCountingRepo

class PositionRepository(_WriteCountingRepo):
    """
    Ожидаем схему:
      positions(id TEXT PK, symbol TEXT, side TEXT, amount REAL, entry_price REAL, status TEXT, opened_at INTEGER, updated_at INTEGER)
      индексы по (status, symbol)
    """

    def upsert(self, position: Dict[str, Any]) -> None:
        pos_id = str(position.get("id") or position.get("pos_id") or "")
        symbol = str(position.get("symbol"))
        side = str(position.get("side"))
        amount = float(position.get("amount", 0.0))
        entry_price = float(position.get("entry_price", 0.0))
        status = str(position.get("status") or "open")
        opened_at = int(position.get("opened_at") or datetime.now(tz=timezone.utc).timestamp())
        updated_at = int(datetime.now(tz=timezone.utc).timestamp())

        cur = self._con.cursor()
        try:
            # REPLACE обеспечивает идемпотентность id
            cur.execute(
                "REPLACE INTO positions(id, symbol, side, amount, entry_price, status, opened_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (pos_id, symbol, side, amount, entry_price, status, opened_at, updated_at),
            )
            self._inc_writes("positions", 1)
        finally:
            cur.close()

    def get_open(self) -> List[Dict[str, Any]]:
        cur = self._con.cursor()
        try:
            cur.execute("SELECT id, symbol, side, amount, entry_price, status, opened_at, updated_at FROM positions WHERE status='open' ORDER BY opened_at DESC")
            rows = cur.fetchall()
            return [
                {"id": r[0], "symbol": r[1], "side": r[2], "amount": r[3], "entry_price": r[4], "status": r[5], "opened_at": r[6], "updated_at": r[7]}
                for r in rows
            ]
        finally:
            cur.close()

    def get_by_id(self, pos_id: str) -> Optional[Dict[str, Any]]:
        cur = self._con.cursor()
        try:
            cur.execute("SELECT id, symbol, side, amount, entry_price, status, opened_at, updated_at FROM positions WHERE id=? LIMIT 1", (pos_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {"id": row[0], "symbol": row[1], "side": row[2], "amount": row[3], "entry_price": row[4], "status": row[5], "opened_at": row[6], "updated_at": row[7]}
        finally:
            cur.close()
