# src/crypto_ai_bot/core/infrastructure/storage/repositories/trades.py
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Dict, List, Optional

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.core.infrastructure.brokers.base import OrderDTO

class TradesRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    # ---- запись сделок ----
    def add_from_order(self, order: OrderDTO) -> int:
        """
        Сохраняет исполненный ордер в trades. Возвращает rowid.
        Поля:
          - cost: переводим в котировку, если возможно (price*filled) — fallback 0
          - fee_quote: берём из order.fee_quote (если не задано — 0)
        """
        if not order or not order.symbol:
            return 0
        ts = int(order.timestamp or now_ms())
        price = dec(str(order.price)) if order.price is not None else dec("0")
        cost = dec(str(order.cost)) if order.cost is not None else (price * dec(str(order.filled or 0)))
        fee_q = dec(str(getattr(order, "fee_quote", "0") or "0"))
        cur = self._c.execute(
            """
            INSERT INTO trades(broker_order_id, client_order_id, symbol, side, amount, price, cost, status, ts_ms, created_at_ms, fee_quote)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                getattr(order, "id", None),
                getattr(order, "client_order_id", None),
                order.symbol,
                (order.side or "").lower(),
                str(dec(str(order.amount or 0))),
                str(price),
                str(cost),
                order.status or "closed",
                ts,
                now_ms(),
                str(fee_q),
            ),
        )
        self._c.commit()
        return int(cur.lastrowid or 0)

    def add_reconciliation_trade(self, row: Dict[str, str]) -> int:
        """
        Техническая запись для аудита при autofix (status='reconciliation').
        row: {symbol, side, amount, ts_ms, client_order_id}
        """
        ts = int(row.get("ts_ms") or now_ms())
        cur = self._c.execute(
            """
            INSERT INTO trades(broker_order_id, client_order_id, symbol, side, amount, price, cost, status, ts_ms, created_at_ms, fee_quote)
            VALUES(NULL,?,?,?,?,0,0,'reconciliation',?, ?, 0)
            """,
            (
                row.get("client_order_id"),
                row["symbol"],
                row["side"],
                str(dec(row["amount"])),
                ts,
                now_ms(),
            ),
        )
        self._c.commit()
        return int(cur.lastrowid or 0)

    # ---- агрегаты для risk ----
    def count_orders_last_minutes(self, symbol: str, minutes: int) -> int:
        window_ms = int(minutes) * 60_000
        cutoff = now_ms() - window_ms
        cur = self._c.execute(
            "SELECT COUNT(1) FROM trades WHERE symbol=? AND ts_ms>=?;",
            (symbol, cutoff),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def daily_pnl_quote(self, symbol: str) -> Decimal:
        """
        PnL за «сегодня» в валюте котировки: сумма (sell.cost - buy.cost) - суммарные fee.
        Привязка к UTC-дню (простая и предсказуемая).
        """
        # границы дня по UTC
        from datetime import datetime, timezone
        now = datetime.now(tz=timezone.utc)
        start = int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp() * 1000)
        cur = self._c.execute(
            """
            SELECT side, COALESCE(cost,0) as cost, COALESCE(fee_quote,0) as fee
            FROM trades WHERE symbol=? AND ts_ms>=?
            """,
            (symbol, start),
        )
        pnl = dec("0")
        fees = dec("0")
        for side, cost, fee in cur.fetchall():
            s = str(side or "").lower()
            c = dec(str(cost))
            f = dec(str(fee))
            if s == "sell":
                pnl += c
            elif s == "buy":
                pnl -= c
            fees += f
        return pnl - fees

    # ---- выборки для API ----
    def list_recent(self, symbol: str, limit: int = 100) -> List[Dict[str, str]]:
        cur = self._c.execute(
            """
            SELECT id, broker_order_id, client_order_id, symbol, side, amount, price, cost, status, ts_ms, fee_quote
            FROM trades WHERE symbol=? ORDER BY ts_ms DESC LIMIT ?
            """,
            (symbol, int(limit)),
        )
        rows = []
        for r in cur.fetchall():
            rows.append({k: r[k] if k in r.keys() else None for k in r.keys()})
        return rows

    def list_today(self, symbol: str) -> List[Dict[str, str]]:
        from datetime import datetime, timezone
        now = datetime.now(tz=timezone.utc)
        start = int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp() * 1000)
        cur = self._c.execute(
            """
            SELECT id, side, amount, price, cost, fee_quote, ts_ms
            FROM trades WHERE symbol=? AND ts_ms>=? ORDER BY ts_ms ASC
            """,
            (symbol, start),
        )
        rows = []
        for r in cur.fetchall():
            rows.append({k: r[k] if k in r.keys() else None for k in r.keys()})
        return rows

# совместимость
TradesRepo = TradesRepository
