# src/crypto_ai_bot/core/storage/repositories/positions.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

def _sdec(v: Decimal | str | float | int | None) -> str | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return str(v)
    return str(v)

@dataclass
class PositionRecord:
    id: str
    symbol: str
    side: str                # "buy"|"sell"
    size_base: Decimal
    entry_price: Decimal
    sl: Optional[Decimal]
    tp: Optional[Decimal]
    opened_at: int           # ms
    status: str              # "open"|"closed"
    updated_at: int          # ms
    realized_pnl: Decimal = Decimal("0")

class PositionRepositorySQLite:
    """
    Позиции: одна строка на позицию. Денежные поля — TEXT (Decimal).
    """

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con

    def upsert(self, p: PositionRecord) -> None:
        self.con.execute(
            """
            INSERT INTO positions (id, symbol, side, size_base, entry_price, sl, tp, opened_at, status, updated_at, realized_pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                symbol=excluded.symbol,
                side=excluded.side,
                size_base=excluded.size_base,
                entry_price=excluded.entry_price,
                sl=excluded.sl,
                tp=excluded.tp,
                status=excluded.status,
                updated_at=excluded.updated_at,
                realized_pnl=excluded.realized_pnl;
            """,
            (
                p.id,
                p.symbol,
                p.side,
                _sdec(p.size_base),
                _sdec(p.entry_price),
                _sdec(p.sl),
                _sdec(p.tp),
                int(p.opened_at),
                p.status,
                int(p.updated_at),
                _sdec(p.realized_pnl),
            ),
        )

    def mark_closed(self, pos_id: str, realized_pnl: Decimal, closed_at_ms: int) -> None:
        self.con.execute(
            """
            UPDATE positions
            SET status='closed',
                realized_pnl=?,
                updated_at=?
            WHERE id=?;
            """,
            (_sdec(realized_pnl), int(closed_at_ms), pos_id),
        )

    def update_size_and_price(self, pos_id: str, new_size: Decimal, new_avg_price: Decimal, realized_pnl: Decimal, ts_ms: int) -> None:
        self.con.execute(
            """
            UPDATE positions
            SET size_base=?,
                entry_price=?,
                realized_pnl=?,
                updated_at=?
            WHERE id=?;
            """,
            (_sdec(new_size), _sdec(new_avg_price), _sdec(realized_pnl), int(ts_ms), pos_id),
        )

    def get_open(self) -> List[Dict[str, Any]]:
        cur = self.con.execute(
            """
            SELECT id, symbol, side, size_base, entry_price, sl, tp, opened_at, status, updated_at, realized_pnl
            FROM positions
            WHERE status='open'
            ORDER BY opened_at ASC;
            """
        )
        return [dict(r) for r in cur.fetchall()]

    def get_by_id(self, pos_id: str) -> Optional[Dict[str, Any]]:
        cur = self.con.execute(
            """
            SELECT id, symbol, side, size_base, entry_price, sl, tp, opened_at, status, updated_at, realized_pnl
            FROM positions
            WHERE id=?;
            """,
            (pos_id,),
        )
        r = cur.fetchone()
        return dict(r) if r else None
