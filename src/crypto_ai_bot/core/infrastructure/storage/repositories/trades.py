from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from crypto_ai_bot.core.infrastructure.brokers.base import OrderDTO
from crypto_ai_bot.utils.time import now_ms


class TradesRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def add_from_order(self, order: OrderDTO) -> Optional[int]:
        """Записать исполненный ордер в таблицу trades (price/cost восстанавливаются при необходимости)."""
        try:
            # восстановление price/cost
            price = order.price
            cost = order.cost
            if price is None and cost is not None and order.filled and order.filled > 0:
                price = cost / order.filled
            if cost is None and price is not None and order.filled and order.filled > 0:
                cost = price * order.filled
            price = price or Decimal("0")
            cost = cost or Decimal("0")

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
                    str(order.filled or order.amount or Decimal("0")),
                    str(price),
                    str(cost),
                    order.status,
                    order.timestamp or now_ms(),
                    now_ms(),
                ),
            )
            return cur.lastrowid if cur.rowcount else None
        except sqlite3.IntegrityError:
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
                t.get("broker_order_id", None),
                t.get("client_order_id", None),
                t["symbol"],
                t["side"],
                str(t["amount"]),
                str(t.get("price", "0")),
                str(t.get("cost", "0")),
                str(t.get("status", "reconciliation")),
                int(t.get("ts_ms", now_ms())),
                now_ms(),
            ),
        )
        return cur.lastrowid

    def list_recent(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        cur = self._c.execute(
            "SELECT id, side, amount, price, cost, ts_ms, status FROM trades WHERE symbol=? ORDER BY ts_ms DESC LIMIT ?",
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

        now = time.time()
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        cur = self._c.execute(
            "SELECT id, side, amount, price, cost, ts_ms, status FROM trades WHERE symbol=? AND ts_ms>=? ORDER BY ts_ms ASC",
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

    def count_orders_last_minutes(self, symbol: str, minutes: int) -> int:
        """Количество ордеров за последние N минут."""
        since = now_ms() - (minutes * 60 * 1000)
        cur = self._c.execute(
            "SELECT COUNT(*) FROM trades WHERE symbol=? AND ts_ms > ?",
            (symbol, since)
        )
        result = cur.fetchone()
        return result[0] if result else 0

    def daily_pnl_quote(self, symbol: str) -> Decimal:
        """PnL за сегодня в quote валюте."""
        from datetime import datetime, timezone
        
        today_start = int(datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp() * 1000)
        
        cur = self._c.execute(
            """
            SELECT SUM(CASE 
                WHEN side='sell' THEN CAST(cost AS REAL)
                WHEN side='buy' THEN -CAST(cost AS REAL)
                ELSE 0 
            END) 
            FROM trades 
            WHERE symbol=? AND ts_ms >= ?
            """,
            (symbol, today_start)
        )
        result = cur.fetchone()
        return Decimal(str(result[0])) if result and result[0] else Decimal("0")


# --- compatibility aliases expected by storage.facade ---
TradesRepo = TradesRepository  # Основной алиас используемый в facade.py