from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Tuple
from datetime import datetime, timezone

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.pnl import fifo_pnl
from .positions import PositionsRepository


def _today_bounds_utc() -> Tuple[int, int]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


@dataclass
class TradesRepository:
    conn: Any  # sqlite3.Connection с row_factory=sqlite3.Row

    def add_from_order(self, order: Any) -> None:
        symbol = getattr(order, "symbol", None)
        side = (getattr(order, "side", "") or "").lower()
        amount = dec(str(getattr(order, "amount", "") or "0"))
        filled = dec(str(getattr(order, "filled", "") or "0"))
        price = dec(str(getattr(order, "price", "") or "0"))
        cost = dec(str(getattr(order, "cost", "") or "0"))
        fee_quote = dec(str(getattr(order, "fee_quote", "") or "0"))
        ts_ms = int(getattr(order, "ts_ms", 0) or 0)

        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO trades (broker_order_id, client_order_id, symbol, side, amount, filled, price, cost, fee_quote, ts_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                getattr(order, "id", None),
                getattr(order, "client_order_id", None),
                symbol, side,
                str(amount), str(filled), str(price), str(cost), str(fee_quote),
                ts_ms,
            ),
        )
        self.conn.commit()

        if symbol:
            if side == "sell":
                base_amount = filled if filled > 0 else amount
            else:
                base_amount = (cost / price) if price > 0 and cost > 0 else (filled if filled > 0 else dec("0"))
            pos_repo = PositionsRepository(self.conn)
            pos_repo.apply_trade(
                symbol=symbol, side=side, base_amount=base_amount,
                price=price, fee_quote=fee_quote, last_price=price,
            )

    def list_today(self, symbol: str) -> List[Dict[str, Any]]:
        ts_from, ts_to = _today_bounds_utc()
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT symbol, side, amount, filled, price, cost, fee_quote, ts_ms
            FROM trades
            WHERE symbol = ? AND ts_ms BETWEEN ? AND ?
            ORDER BY ts_ms ASC
            """,
            (symbol, ts_from, ts_to),
        )
        rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append({
                "symbol": r["symbol"],
                "side": r["side"],
                "amount": r["amount"],
                "filled": r["filled"],
                "price": r["price"],
                "cost": r["cost"],
                "fee_quote": r["fee_quote"],
                "ts_ms": r["ts_ms"],
            })
        return out

    def daily_turnover_quote(self, symbol: str) -> Decimal:
        rows = self.list_today(symbol)
        total = dec("0")
        for r in rows:
            total += dec(str(r.get("cost", "0") or "0"))
        return total

    def count_orders_last_minutes(self, symbol: str, minutes: int) -> int:
        cur = self.conn.cursor()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        from_ms = now_ms - int(minutes * 60 * 1000)
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM trades WHERE symbol = ? AND ts_ms >= ?",
            (symbol, from_ms),
        )
        row = cur.fetchone()
        return int(row["cnt"] if row and "cnt" in row.keys() else 0)

    def add_reconciliation_trade(self, data: Dict[str, Any]) -> None:
        symbol = data.get("symbol")
        side = (data.get("side", "") or "").lower()
        amount = dec(str(data.get("amount", "") or "0"))
        filled = dec(str(data.get("filled", "") or "0"))
        price = dec(str(data.get("price", "") or "0"))
        cost = dec(str(data.get("cost", "") or "0"))
        fee_quote = dec(str(data.get("fee_quote", "") or "0"))
        ts_ms = int(data.get("ts_ms", 0) or 0)

        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO trades (broker_order_id, client_order_id, symbol, side, amount, filled, price, cost, fee_quote, ts_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("broker_order_id"),
                data.get("client_order_id"),
                symbol, side,
                str(amount), str(filled), str(price), str(cost), str(fee_quote),
                ts_ms,
            ),
        )
        self.conn.commit()

        if symbol:
            if side == "sell":
                base_amount = filled if filled > 0 else amount
            else:
                base_amount = (cost / price) if price > 0 and cost > 0 else (filled if filled > 0 else dec("0"))
            pos_repo = PositionsRepository(self.conn)
            pos_repo.apply_trade(
                symbol=symbol, side=side, base_amount=base_amount,
                price=price, fee_quote=fee_quote, last_price=price,
            )

    def realized_pnl_day_quote(self, symbol: str) -> Decimal:
        rows = self.list_today(symbol)
        trades: List[dict] = []
        for r in rows:
            side = str(r.get("side", "")).lower()
            price = dec(str(r.get("price", "0") or "0"))
            cost = dec(str(r.get("cost", "0") or "0"))
            amount = dec(str(r.get("amount", "0") or "0"))
            filled = dec(str(r.get("filled", "0") or "0"))
            if side == "sell":
                base_amount = filled if filled > 0 else amount
            else:
                base_amount = (cost / price) if price > 0 and cost > 0 else (filled if filled > 0 else dec("0"))
            trades.append({
                "side": side,
                "base_amount": base_amount,
                "price": price,
                "fee_quote": dec(str(r.get("fee_quote", "0") or "0")),
                "ts_ms": int(r.get("ts_ms") or 0),
            })
        return fifo_pnl(trades).realized_quote

    def daily_pnl_quote(self, symbol: str) -> Decimal:
        return self.realized_pnl_day_quote(symbol)
