# src/crypto_ai_bot/core/storage/repositories/trades.py
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

def _sdec(v: Decimal | str | float | int | None) -> str | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return str(v)
    return str(v)

@dataclass
class TradeRecord:
    id: str
    symbol: str
    side: str
    type: str
    amount_base: Decimal
    price: Decimal
    fee_quote: Decimal
    fee_currency: str
    timestamp: int  # ms
    position_id: Optional[str] = None
    client_order_id: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None

class TradeRepositorySQLite:
    """
    Хранение сделок. Все денежные поля — TEXT (Decimal сериализация), время — ms (INTEGER).
    Уникальность по id и client_order_id (если задан).
    """

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con

    def insert(self, tr: TradeRecord) -> None:
        self.con.execute(
            """
            INSERT INTO trades (id, position_id, symbol, side, type, amount_base, price, fee_quote, fee_currency, timestamp, client_order_id, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING;
            """,
            (
                tr.id,
                tr.position_id,
                tr.symbol,
                tr.side,
                tr.type,
                _sdec(tr.amount_base),
                _sdec(tr.price),
                _sdec(tr.fee_quote),
                tr.fee_currency,
                int(tr.timestamp),
                tr.client_order_id,
                json.dumps(tr.extra or {}, ensure_ascii=False),
            ),
        )

    def upsert_by_client_order_id(self, client_order_id: str, tr: TradeRecord) -> None:
        """
        Идемпотентная вставка по client_order_id. Если уже есть — ничего не меняем.
        """
        self.con.execute(
            """
            INSERT INTO trades (id, position_id, symbol, side, type, amount_base, price, fee_quote, fee_currency, timestamp, client_order_id, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_order_id) DO NOTHING;
            """,
            (
                tr.id,
                tr.position_id,
                tr.symbol,
                tr.side,
                tr.type,
                _sdec(tr.amount_base),
                _sdec(tr.price),
                _sdec(tr.fee_quote),
                tr.fee_currency,
                int(tr.timestamp),
                client_order_id,
                json.dumps(tr.extra or {}, ensure_ascii=False),
            ),
        )

    def list_recent(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        cur = self.con.execute(
            """
            SELECT id, position_id, symbol, side, type, amount_base, price, fee_quote, fee_currency, timestamp, client_order_id, extra
            FROM trades
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?;
            """,
            (symbol, int(limit)),
        )
        rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "position_id": r["position_id"],
                    "symbol": r["symbol"],
                    "side": r["side"],
                    "type": r["type"],
                    "amount_base": r["amount_base"],
                    "price": r["price"],
                    "fee_quote": r["fee_quote"],
                    "fee_currency": r["fee_currency"],
                    "timestamp": int(r["timestamp"]),
                    "client_order_id": r["client_order_id"],
                    "extra": json.loads(r["extra"] or "{}"),
                }
            )
        return out
