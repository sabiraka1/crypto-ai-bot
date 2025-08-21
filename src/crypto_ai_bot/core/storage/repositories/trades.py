from __future__ import annotations
import sqlite3
from typing import Iterable, Optional
from dataclasses import asdict

from crypto_ai_bot.core.storage.repositories import ensure_schema
from crypto_ai_bot.core.brokers.base import OrderDTO


class TradesRepositoryImpl:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        ensure_schema(self.conn)

    def create_pending_order(self, order: OrderDTO) -> None:
        # Вставляем как 'open' (если нужно) — но интерфейс подразумевает любой статус; используем order.status
        self.conn.execute(
            """            INSERT OR REPLACE INTO trades (id, client_order_id, symbol, side, type, amount, price, status, ts_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                order.id,
                order.client_order_id,
                order.symbol,
                order.side,
                order.type,
                order.amount if order.side == "buy" else -abs(order.amount),
                order.price,
                order.status,
                0,
            ),
        )
        self.conn.commit()

    def record_exchange_update(self, order: OrderDTO) -> None:
        # Обновляем запись статуса/цены/времени (или вставляем, если ещё не было)
        self.conn.execute(
            """
            INSERT INTO trades (id, client_order_id, symbol, side, type, amount, price, status, ts_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                client_order_id=excluded.client_order_id,
                symbol=excluded.symbol,
                side=excluded.side,
                type=excluded.type,
                amount=excluded.amount,
                price=excluded.price,
                status=excluded.status,
                ts_ms=excluded.ts_ms;
            """,
            (
                order.id,
                order.client_order_id,
                order.symbol,
                order.side,
                order.type,
                order.amount if order.side == "buy" else -abs(order.amount),
                order.price,
                order.status,
                getattr(order, "ts_ms", 0) or 0,
            ),
        )
        self.conn.commit()

    def get_realized_pnl(self, *, symbol: str | None = None) -> float:
        """Очень простой FIFO PnL по закрытым сделкам (sell против накопленных buy).
        Предполагаем spot: buy положительный amount, sell отрицательный.
        """
        cur = self.conn.cursor()
        if symbol:
            cur.execute("SELECT amount, price FROM trades WHERE symbol=? AND status='closed' ORDER BY ts_ms ASC", (symbol,))
        else:
            cur.execute("SELECT amount, price, symbol FROM trades WHERE status='closed' ORDER BY symbol, ts_ms ASC")
        rows = cur.fetchall()
        cur.close()

        pnl = 0.0
        # Накапливаем по каждому символу
        buffers: dict[str, list[tuple[float, float]]] = {}
        for row in rows:
            if symbol:
                amt, price = row
                sym = symbol
            else:
                amt, price, sym = row
            buf = buffers.setdefault(sym, [])
            if amt > 0:  # покупка
                buf.append((amt, price))
            else:  # продажа
                sell_qty = -amt
                remain = sell_qty
                while remain > 1e-12 and buf:
                    buy_qty, buy_price = buf[0]
                    take = min(buy_qty, remain)
                    pnl += (price - buy_price) * take
                    buy_qty -= take
                    remain -= take
                    if buy_qty <= 1e-12:
                        buf.pop(0)
                    else:
                        buf[0] = (buy_qty, buy_price)
                # если remain > 0 — продали больше, чем купили; считаем, что остальное без базы (игнор)
        return float(pnl)
