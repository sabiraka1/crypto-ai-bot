from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Iterable, Tuple
from datetime import datetime, timezone

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.pnl import fifo_pnl


def _today_bounds_utc() -> Tuple[int, int]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    # предполагаем, что в БД хранится ts_ms (UTC milliseconds)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


@dataclass
class TradesRepository:
    conn: Any  # sqlite3.Connection (row_factory = sqlite3.Row)

    # ----------------- ПУБЛИЧНЫЙ API (как было) -----------------

    def add_from_order(self, order: Any) -> None:
        """
        Сохранение ордера как трейда.
        Ожидаемые поля: id, client_order_id, side, amount, filled, price, cost, fee_quote?, symbol?, ts_ms?
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO trades (broker_order_id, client_order_id, symbol, side, amount, filled, price, cost, fee_quote, ts_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                getattr(order, "id", None),
                getattr(order, "client_order_id", None),
                getattr(order, "symbol", None),
                getattr(order, "side", None),
                str(getattr(order, "amount", None) or ""),
                str(getattr(order, "filled", None) or ""),
                str(getattr(order, "price", None) or ""),
                str(getattr(order, "cost", None) or ""),
                str(getattr(order, "fee_quote", None) or ""),
                int(getattr(order, "ts_ms", None) or 0),
            ),
        )
        self.conn.commit()

    def list_today(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Список сделок за сегодня по символу. Возвращает dict со всеми необходимыми полями для отчётов.
        """
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
        """
        Дневной оборот в котируемой валюте (сумма cost покупок и продаж).
        """
        rows = self.list_today(symbol)
        total = dec("0")
        for r in rows:
            total += dec(str(r.get("cost", "0") or "0"))
        return total

    def count_orders_last_minutes(self, symbol: str, minutes: int) -> int:
        """
        Подсчёт числа ордеров за последние N минут.
        """
        cur = self.conn.cursor()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        from_ms = now_ms - int(minutes * 60 * 1000)
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM trades
            WHERE symbol = ? AND ts_ms >= ?
            """,
            (symbol, from_ms),
        )
        row = cur.fetchone()
        return int(row["cnt"] if row and "cnt" in row.keys() else 0)

    def add_reconciliation_trade(self, data: Dict[str, Any]) -> None:
        """
        Запись спец-сделки от reconcile. Поля ожидаются такие же, как в add_from_order.
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO trades (broker_order_id, client_order_id, symbol, side, amount, filled, price, cost, fee_quote, ts_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("broker_order_id"),
                data.get("client_order_id"),
                data.get("symbol"),
                data.get("side"),
                str(data.get("amount", "")),
                str(data.get("filled", "")),
                str(data.get("price", "")),
                str(data.get("cost", "")),
                str(data.get("fee_quote", "")),
                int(data.get("ts_ms", 0)),
            ),
        )
        self.conn.commit()

    # ----------------- НОВЫЕ МЕТОДЫ: ЕДИНАЯ ТОЧКА PnL -----------------

    def realized_pnl_day_quote(self, symbol: str) -> Decimal:
        """
        FIFO-PnL за сегодня по symbol.
        Реализованный PnL в котируемой валюте (учитывает комиссии fee_quote).
        """
        rows = self.list_today(symbol)
        # Преобразуем строки из БД к ожидаемой схеме fifo_pnl.
        trades: List[dict] = []
        for r in rows:
            side = str(r.get("side", "")).lower()
            price = dec(str(r.get("price", "0") or "0"))
            cost = dec(str(r.get("cost", "0") or "0"))
            # Определяем base_amount (см. normalize в utils/pnl.py)
            # Для sell amount обычно base; для buy — amount может быть quote, поэтому base = cost/price.
            amount = dec(str(r.get("amount", "0") or "0"))
            filled = dec(str(r.get("filled", "0") or "0"))
            base_amount = None
            if side == "sell":
                base_amount = filled if filled > 0 else amount
            else:  # buy
                if price > 0 and cost > 0:
                    base_amount = cost / price
                else:
                    base_amount = filled if filled > 0 else dec("0")
            trades.append({
                "side": side,
                "base_amount": base_amount,
                "price": price,
                "fee_quote": dec(str(r.get("fee_quote", "0") or "0")),
                "ts_ms": int(r.get("ts_ms") or 0),
            })
        res = fifo_pnl(trades)
        return res.realized_quote

    def daily_pnl_quote(self, symbol: str) -> Decimal:
        """
        Для совместимости: возвращаем реализованный FIFO-PnL как дневной PnL.
        При необходимости можно расширить до net-PnL.
        """
        return self.realized_pnl_day_quote(symbol)
