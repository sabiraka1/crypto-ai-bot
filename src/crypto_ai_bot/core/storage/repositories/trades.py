## `core/storage/repositories/trades.py`
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional
from ....utils.time import now_ms
from ....utils.exceptions import ValidationError
from ....utils.ids import sanitize_ascii
from ...brokers.base import OrderDTO
@dataclass(frozen=True)
class TradeRow:
    id: int
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: str
    amount: Decimal
    price: Decimal
    cost: Decimal
    status: str
    ts_ms: int
    created_at_ms: int
class TradesRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn
    def add_from_order(self, order: OrderDTO) -> Optional[int]:
        """Записать исполненный ордер в таблицу trades.
        Возвращает ID вставленной записи или None, если запись уже есть по client_order_id.
        """
        if not order.client_order_id:
            raise ValidationError("order.client_order_id is required")
        try:
            cur = self._c.execute(
                """
                INSERT OR IGNORE INTO trades (
                    broker_order_id, client_order_id, symbol, side, amount, price, cost, status, ts_ms, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.id,
                    sanitize_ascii(order.client_order_id),
                    order.symbol,
                    order.side,
                    str(order.amount),
                    str(order.price),
                    str(order.cost),
                    order.status,
                    order.timestamp,
                    now_ms(),
                ),
            )
            return cur.lastrowid if cur.rowcount else None
        except sqlite3.IntegrityError:
            return None
    def find_by_client_order_id(self, client_order_id: str) -> Optional[TradeRow]:
        cur = self._c.execute(
            "SELECT id, broker_order_id, client_order_id, symbol, side, amount, price, cost, status, ts_ms, created_at_ms\n"
            "FROM trades WHERE client_order_id = ?",
            (client_order_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return TradeRow(
            id=row[0], broker_order_id=row[1] or "", client_order_id=row[2], symbol=row[3], side=row[4],
            amount=Decimal(str(row[5])), price=Decimal(str(row[6])), cost=Decimal(str(row[7])),
            status=row[8], ts_ms=int(row[9]), created_at_ms=int(row[10])
        )
    def list_recent(self, symbol: Optional[str] = None, limit: int = 100) -> List[TradeRow]:
        if symbol:
            cur = self._c.execute(
                "SELECT id, broker_order_id, client_order_id, symbol, side, amount, price, cost, status, ts_ms, created_at_ms\n"
                "FROM trades WHERE symbol = ? ORDER BY ts_ms DESC LIMIT ?",
                (symbol, limit),
            )
        else:
            cur = self._c.execute(
                "SELECT id, broker_order_id, client_order_id, symbol, side, amount, price, cost, status, ts_ms, created_at_ms\n"
                "FROM trades ORDER BY ts_ms DESC LIMIT ?",
                (limit,),
            )
        rows = cur.fetchall()
        out: List[TradeRow] = []
        for r in rows:
            out.append(
                TradeRow(
                    id=r[0], broker_order_id=r[1] or "", client_order_id=r[2], symbol=r[3], side=r[4],
                    amount=Decimal(str(r[5])), price=Decimal(str(r[6])), cost=Decimal(str(r[7])),
                    status=r[8], ts_ms=int(r[9]), created_at_ms=int(r[10])
                )
            )
        return out