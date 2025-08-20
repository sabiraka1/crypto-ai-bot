# src/crypto_ai_bot/core/storage/repositories/trades.py
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.core._time import now_ms


class SqliteTradeRepository:
    """
    Хранилище сделок (trades) + утилиты reconcile.
    Поддерживает:
      - create_pending_order(...)
      - update_client_order_id(order_id, client_order_id)
      - record_exchange_update(order_id, raw)
      - get_by_exchange_order_id(order_id)
    Схема самопроверяется на наличие client_order_id.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                created_ms          INTEGER NOT NULL,
                updated_ms          INTEGER NOT NULL,
                symbol              TEXT NOT NULL,
                side                TEXT NOT NULL,             -- 'buy' | 'sell'
                state               TEXT NOT NULL DEFAULT 'pending', -- 'pending'|'partial'|'filled'|'canceled'
                exp_price           REAL DEFAULT 0,            -- ожидаемая цена (для аудита/метрик)
                qty                 REAL DEFAULT 0,            -- запрошенное количество (для sell) или 0 для buy
                filled_qty          REAL DEFAULT 0,
                avg_price           REAL DEFAULT 0,
                fee_amt             REAL DEFAULT 0,
                fee_ccy             TEXT,
                exchange_order_id   TEXT,                      -- id ордера на бирже
                client_order_id     TEXT,                      -- Gate.io 'text' / CCXT 'clientOrderId'
                raw                 TEXT                       -- последний «raw» от биржи (JSON)
            );
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_exchange_order_id ON trades(exchange_order_id);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_client_order_id ON trades(client_order_id);")
        self.conn.commit()

        # Самодиагностика: если колонка отсутствует (старые БД), добавим.
        self._maybe_add_column("trades", "client_order_id", "TEXT")
        self.conn.commit()

    # ------------------------------ schema helpers ---------------------------

    def _maybe_add_column(self, table: str, column: str, decl: str) -> None:
        cur = self.conn.execute(f"PRAGMA table_info({table});")
        cols = [r[1] for r in cur.fetchall()]  # name in col#2
        if column not in cols:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl};")
            if column == "client_order_id":
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_client_order_id ON trades(client_order_id);")

    # ------------------------------ CRUD -------------------------------------

    def create_pending_order(
        self,
        *,
        symbol: str,
        side: str,                  # 'buy' | 'sell'
        exp_price: float,
        qty: float,
        order_id: str,              # exchange order id (если ещё неизвестен, можно 'unknown')
        client_order_id: Optional[str] = None,
    ) -> int:
        ts = now_ms()
        cur = self.conn.execute(
            """
            INSERT INTO trades (created_ms, updated_ms, symbol, side, state, exp_price, qty,
                                exchange_order_id, client_order_id)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?);
            """,
            (ts, ts, symbol, side, float(exp_price), float(qty), order_id, client_order_id),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_client_order_id(self, *, order_id: str, client_order_id: str) -> bool:
        """
        Проставляет client_order_id для записи, найденной по exchange_order_id.
        Возвращает True, если апдейт затронул строку.
        """
        cur = self.conn.execute(
            """
            UPDATE trades
               SET client_order_id = ?, updated_ms = ?
             WHERE exchange_order_id = ?;
            """,
            (client_order_id, now_ms(), order_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def record_exchange_update(self, *, order_id: str, raw: Dict[str, Any]) -> None:
        """
        Обновляет состояние записи по «сырому» ответу биржи.
        Понимает поля CCXT/Gate: status/state, filled, amount, average/price, fee, clientOrderId/text.
        """
        ts = now_ms()
        state, filled_qty, avg_price, fee_amt, fee_ccy = self._parse_raw_state(raw)
        coid = raw.get("clientOrderId") or raw.get("text")

        # если вдруг ордер неизвестен — создать каркас (безопасная защита)
        if not self._exists_by_exchange_order_id(order_id):
            self.conn.execute(
                """
                INSERT INTO trades (created_ms, updated_ms, symbol, side, state, exp_price, qty,
                                    exchange_order_id, client_order_id, filled_qty, avg_price, fee_amt, fee_ccy, raw)
                VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    ts, ts,
                    raw.get("symbol") or raw.get("symbolNormalized") or "UNKNOWN",
                    (raw.get("side") or "buy").lower(),
                    state,
                    order_id,
                    coid,
                    filled_qty,
                    avg_price,
                    fee_amt,
                    fee_ccy,
                    json.dumps(raw, ensure_ascii=False),
                ),
            )
            self.conn.commit()
            return

        # обычный путь: апдейт существующей записи
        self.conn.execute(
            """
            UPDATE trades
               SET updated_ms = ?,
                   state = COALESCE(?, state),
                   filled_qty = COALESCE(?, filled_qty),
                   avg_price = COALESCE(?, avg_price),
                   fee_amt = COALESCE(?, fee_amt),
                   fee_ccy = COALESCE(?, fee_ccy),
                   client_order_id = COALESCE(?, client_order_id),
                   raw = ?
             WHERE exchange_order_id = ?;
            """,
            (
                ts,
                state,
                filled_qty,
                avg_price,
                fee_amt,
                fee_ccy,
                coid,
                json.dumps(raw, ensure_ascii=False),
                order_id,
            ),
        )
        self.conn.commit()

    def get_by_exchange_order_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT id, created_ms, updated_ms, symbol, side, state, exp_price, qty, "
            "filled_qty, avg_price, fee_amt, fee_ccy, exchange_order_id, client_order_id, raw "
            "FROM trades WHERE exchange_order_id = ? LIMIT 1;",
            (order_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return {c: row[i] for i, c in enumerate(cols)}

    # ------------------------------ internals --------------------------------

    def _exists_by_exchange_order_id(self, order_id: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM trades WHERE exchange_order_id = ? LIMIT 1;", (order_id,))
        return cur.fetchone() is not None

    @staticmethod
    def _parse_raw_state(raw: Dict[str, Any]) -> Tuple[Optional[str], Optional[float], Optional[float], Optional[float], Optional[str]]:
        """
        Преобразует CCXT/Gate структуру в внутреннее состояние.
        Возвращает: (state, filled_qty, avg_price, fee_amt, fee_ccy)
        """
        # filled / amount
        filled = raw.get("filled")
        amount = raw.get("amount")
        filled_qty = float(filled) if filled is not None else None

        # средняя цена
        avg = raw.get("average")
        price = raw.get("price")
        avg_price = float(avg if avg is not None else (price if price is not None else 0)) or None

        # статус
        status = (raw.get("status") or raw.get("state") or "").lower()
        if status in {"closed", "filled"}:
            state = "filled"
        elif status in {"canceled", "cancelled", "expired"}:
            state = "canceled"
        elif status in {"open", "partial"}:
            # если знаем filled/amount — различим partial
            if filled is not None and amount is not None:
                try:
                    state = "partial" if float(filled) < float(amount) else "filled"
                except Exception:
                    state = "open"
            else:
                state = "open"
        else:
            state = None  # не менять

        # комиссия
        fee_amt = None
        fee_ccy = None
        fee = raw.get("fee")
        if isinstance(fee, dict):
            v = fee.get("cost")
            c = fee.get("currency")
            try:
                fee_amt = float(v) if v is not None else None
                fee_ccy = str(c) if c is not None else None
            except Exception:
                pass

        return state, filled_qty, avg_price, fee_amt, fee_ccy
