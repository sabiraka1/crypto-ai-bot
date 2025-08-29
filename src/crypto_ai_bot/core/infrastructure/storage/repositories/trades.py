# src/crypto_ai_bot/core/infrastructure/storage/repositories/trades.py
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from ...brokers.base import OrderDTO
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.decimal import dec


class TradesRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn
        # ensure table exists (idempotent)
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker_order_id TEXT,
                client_order_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,               -- 'buy' | 'sell'
                amount TEXT NOT NULL,             -- Decimal as str
                price TEXT NOT NULL,              -- Decimal as str
                cost  TEXT NOT NULL,              -- Decimal as str (quote)
                status TEXT NOT NULL,             -- 'closed' | 'reconciliation' | etc.
                ts_ms INTEGER NOT NULL,
                created_at_ms INTEGER NOT NULL
            )
            """
        )
        self._c.commit()

    def add_from_order(self, order: OrderDTO) -> Optional[int]:
        """Записать исполненный ордер в trades (восстанавливая price/cost при необходимости)."""
        try:
            # восстановление price/cost
            price = order.price
            cost = order.cost
            if price is None and cost is not None and order.filled and order.filled > 0:
                price = cost / order.filled
            if cost is None and price is not None and order.filled and order.filled > 0:
                cost = price * order.filled
            price = price or dec("0")
            cost = cost or dec("0")

            cur = self._c.execute(
                """
                INSERT OR IGNORE INTO trades (
                    broker_order_id, client_order_id, symbol, side,
                    amount, price, cost, status, ts_ms, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.id,
                    order.client_order_id,
                    order.symbol,
                    order.side,
                    str(order.filled or order.amount or dec("0")),
                    str(price),
                    str(cost),
                    order.status or "closed",
                    int(order.timestamp or now_ms()),
                    now_ms(),
                ),
            )
            self._c.commit()
            return cur.lastrowid if cur.rowcount else None
        except sqlite3.IntegrityError:
            self._c.rollback()
            return None

    def add_reconciliation_trade(self, t: Dict[str, Any]) -> Optional[int]:
        """Записать виртуальную сделку для авто-сверки (status='reconciliation')."""
        cur = self._c.execute(
            """
            INSERT INTO trades (broker_order_id, client_order_id, symbol, side,
                                amount, price, cost, status, ts_ms, created_at_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                t.get("broker_order_id"),
                t.get("client_order_id"),
                str(t["symbol"]),
                str(t["side"]),
                str(t["amount"]),
                str(t.get("price", "0")),
                str(t.get("cost", "0")),
                str(t.get("status", "reconciliation")),
                int(t.get("ts_ms", now_ms())),
                now_ms(),
            ),
        )
        self._c.commit()
        return cur.lastrowid

    def list_recent(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        cur = self._c.execute(
            "SELECT id, side, amount, price, cost, ts_ms, status "
            "FROM trades WHERE symbol=? ORDER BY ts_ms DESC LIMIT ?",
            (symbol, int(limit)),
        )
        rows = cur.fetchall()
        return [
            {
                "id": int(r["id"]),
                "side": str(r["side"]),
                "amount": str(r["amount"]),
                "price": str(r["price"]),
                "cost": str(r["cost"]),
                "ts_ms": int(r["ts_ms"]),
                "status": str(r["status"]),
            }
            for r in rows
        ]

    def list_today(self, symbol: str) -> List[Dict[str, Any]]:
        # простая выборка "сегодня" по UTC-суткам
        import time
        from datetime import datetime, timezone

        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        cur = self._c.execute(
            "SELECT id, side, amount, price, cost, ts_ms, status "
            "FROM trades WHERE symbol=? AND ts_ms>=? ORDER BY ts_ms ASC",
            (symbol, int(start * 1000)),
        )
        rows = cur.fetchall()
        return [
            {
                "id": int(r["id"]),
                "side": str(r["side"]),
                "amount": str(r["amount"]),
                "price": str(r["price"]),
                "cost": str(r["cost"]),
                "ts_ms": int(r["ts_ms"]),
                "status": str(r["status"]),
            }
            for r in rows
        ]

    # === Новые методы для risk/отчётности ===

    def count_orders_last_minutes(self, symbol: str, minutes: int) -> int:
        """Количество сделок за последние N минут (любой статус, кроме явных ошибок)."""
        cutoff = now_ms() - int(minutes) * 60_000
        cur = self._c.execute(
            "SELECT COUNT(1) AS c FROM trades WHERE symbol=? AND ts_ms>=? AND status != 'failed'",
            (symbol, cutoff),
        )
        row = cur.fetchone()
        return int(row["c"] if row and "c" in row.keys() else (row[0] if row else 0))

    def daily_pnl_quote(self, symbol: str) -> Decimal:
        """PNL за сегодня в QUOTE: sum(sell.cost) - sum(buy.cost) по UTC-дню."""
        rows = self.list_today(symbol)
        buys = sum(dec(r["cost"]) for r in rows if str(r["side"]).lower() == "buy")
        sells = sum(dec(r["cost"]) for r in rows if str(r["side"]).lower() == "sell")
        return sells - buys


# --- compatibility aliases (как и было в репо) ---
try:
    TradesRepo  # already defined
except NameError:
    try:
        TradesRepo = TradesRepository  # type: ignore[name-defined]
    except NameError:
        pass
