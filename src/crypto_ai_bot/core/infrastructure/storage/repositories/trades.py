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
        self._c.row_factory = sqlite3.Row

    # ---- запись ----
    def add_from_order(self, order: OrderDTO) -> int:
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

    # ---- агрегаты / выборки ----
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
        pnl = dec("0"); fees = dec("0")
        for side, cost, fee in cur.fetchall():
            s = str(side or "").lower()
            c = dec(str(cost)); f = dec(str(fee))
            if s == "sell": pnl += c
            elif s == "buy": pnl -= c
            fees += f
        return pnl - fees

    def list_recent(self, symbol: str, limit: int = 100) -> List[Dict[str, str]]:
        cur = self._c.execute(
            """
            SELECT id, broker_order_id, client_order_id, symbol, side, amount, price, cost, status, ts_ms, fee_quote
            FROM trades WHERE symbol=? ORDER BY ts_ms DESC LIMIT ?
            """,
            (symbol, int(limit)),
        )
        return [dict(r) for r in cur.fetchall()]

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
        return [dict(r) for r in cur.fetchall()]

    # ---- пост-фактум обогащение ----
    def list_missing_fees(self, symbol: str, since_ms: int, limit: int = 50) -> List[Dict[str, str]]:
        cur = self._c.execute(
            """
            SELECT id, broker_order_id, client_order_id, symbol, side, amount, price, cost, ts_ms, fee_quote
            FROM trades
            WHERE symbol=? AND ts_ms>=? AND COALESCE(fee_quote,0)=0 AND status!='reconciliation'
            ORDER BY ts_ms DESC
            LIMIT ?
            """,
            (symbol, int(since_ms), int(limit)),
        )
        return [dict(r) for r in cur.fetchall()]

    def list_unbound_trades(self, symbol: str, since_ms: int, limit: int = 50) -> List[Dict[str, str]]:
        """Локальные сделки без broker_order_id, но с client_order_id."""
        cur = self._c.execute(
            """
            SELECT id, broker_order_id, client_order_id, symbol, side, amount, price, cost, ts_ms, fee_quote
            FROM trades
            WHERE symbol=? AND ts_ms>=? AND (broker_order_id IS NULL OR broker_order_id='')
                  AND client_order_id IS NOT NULL AND client_order_id!='' AND status!='reconciliation'
            ORDER BY ts_ms DESC
            LIMIT ?
            """,
            (symbol, int(since_ms), int(limit)),
        )
        return [dict(r) for r in cur.fetchall()]

    def set_fee_by_id(self, row_id: int, fee_quote: Decimal) -> None:
        self._c.execute("UPDATE trades SET fee_quote=? WHERE id=?;", (str(dec(str(fee_quote))), int(row_id)))
        self._c.commit()

    def update_price_cost_by_id(self, row_id: int, price: Decimal, cost: Decimal) -> None:
        self._c.execute("UPDATE trades SET price=?, cost=? WHERE id=?;", (str(dec(str(price))), str(dec(str(cost))), int(row_id)))
        self._c.commit()

    def bind_broker_order(self, row_id: int, *, broker_order_id: str, price: Optional[Decimal] = None, cost: Optional[Decimal] = None, fee_quote: Optional[Decimal] = None) -> None:
        sets = ["broker_order_id=?"]; args = [str(broker_order_id)]
        if price is not None: sets.append("price=?"); args.append(str(dec(str(price))))
        if cost  is not None: sets.append("cost=?"); args.append(str(dec(str(cost))))
        if fee_quote is not None: sets.append("fee_quote=?"); args.append(str(dec(str(fee_quote))))
        args.append(int(row_id))
        self._c.execute(f"UPDATE trades SET {', '.join(sets)} WHERE id=?;", args)
        self._c.commit()

# совместимость
TradesRepo = TradesRepository
