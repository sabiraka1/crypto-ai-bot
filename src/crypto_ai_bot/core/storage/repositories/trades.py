# src/crypto_ai_bot/core/storage/repositories/trades.py
import sqlite3
import time
from typing import Dict, Any, List, Optional, Tuple

# Допустимые состояния:
# 'pending' -> 'partial' -> 'filled'
# 'pending' ---------> 'canceled' | 'rejected'
# 'partial' ---------> 'filled'   | 'canceled' | 'rejected'

_TERMINAL = {"filled", "canceled", "rejected"}


class SqliteTradeRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.execute("PRAGMA foreign_keys = ON;")
        self._ensure_schema()

    # ---------- Страхующая инициализация схемы (на случай первого старта без миграторов) ----------

    def _ensure_schema(self) -> None:
        # Базовая таблица (включая все поля, которые используются кодом)
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                qty REAL NOT NULL,
                pnl REAL DEFAULT 0.0,
                order_id TEXT UNIQUE,
                state TEXT DEFAULT 'pending',
                exp_qty REAL DEFAULT 0.0,
                fee_amt REAL DEFAULT 0.0,
                fee_ccy TEXT DEFAULT 'USDT',
                last_exchange_status TEXT,
                last_update_ts INTEGER DEFAULT (strftime('%s','now'))
            );
            """
        )
        # Досоздание недостающих столбцов, если база старая
        cur = self.con.execute("PRAGMA table_info('trades');")
        existing_cols = {row[1] for row in cur.fetchall()}

        def add_col(name: str, ddl: str) -> None:
            if name not in existing_cols:
                self.con.execute(f"ALTER TABLE trades ADD COLUMN {ddl};")

        add_col("order_id", "order_id TEXT UNIQUE")
        add_col("state", "state TEXT DEFAULT 'pending'")
        add_col("exp_qty", "exp_qty REAL DEFAULT 0.0")
        add_col("fee_amt", "fee_amt REAL DEFAULT 0.0")
        add_col("fee_ccy", "fee_ccy TEXT DEFAULT 'USDT'")
        add_col("last_exchange_status", "last_exchange_status TEXT")
        add_col("last_update_ts", "last_update_ts INTEGER DEFAULT (strftime('%s','now'))")

        # Индекс по order_id
        self.con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id);")

    # ---------- Совместимость со старым кодом ----------

    def insert_trade(self, symbol: str, side: str, price: float, qty: float, pnl: float = 0.0) -> int:
        with self.con:
            cur = self.con.execute(
                "INSERT INTO trades(ts, symbol, side, price, qty, pnl, state) VALUES(?,?,?,?,?,?, 'filled')",
                (int(time.time()), symbol, side, float(price), float(qty), float(pnl))
            )
            return int(cur.lastrowid)

    # ---------- Создание/поиск ----------

    def create_pending_order(self, *, symbol: str, side: str, exp_price: float, qty: float, order_id: str) -> int:
        """
        Создаём запись о предполагаемом ордере. Храним exp_qty — ожидаемое, qty=0 (фактически исполненное).
        """
        now = int(time.time())
        with self.con:
            cur = self.con.execute(
                "INSERT OR REPLACE INTO trades(ts, symbol, side, price, qty, pnl, order_id, state, exp_qty, last_exchange_status, last_update_ts) "
                "VALUES(?,?,?,?,?,?,?, 'pending', ?, NULL, ?)",
                (now, symbol, side, float(exp_price), 0.0, 0.0, order_id, float(qty), now)
            )
            return int(cur.lastrowid)

    def get_by_order_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        cur = self.con.execute(
            "SELECT id, ts, symbol, side, price, qty, pnl, order_id, state, exp_qty, fee_amt, fee_ccy, last_exchange_status, last_update_ts "
            "FROM trades WHERE order_id=?",
            (order_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    def find_pending_orders(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        q = ("SELECT id, ts, symbol, side, price, qty, order_id, state, exp_qty "
             "FROM trades WHERE state IN ('pending','partial')")
        p: List[Any] = []
        if symbol:
            q += " AND symbol=?"
            p.append(symbol)
        q += " ORDER BY ts ASC LIMIT ?"
        p.append(max(1, int(limit)))
        cur = self.con.execute(q, tuple(p))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def list_by_symbol(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        limit = max(1, int(limit))
        cur = self.con.execute(
            "SELECT id, ts, symbol, side, price, qty, pnl, order_id, state, fee_amt, fee_ccy, exp_qty "
            "FROM trades WHERE symbol = ? ORDER BY ts DESC LIMIT ?",
            (symbol, limit)
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def count_pending(self) -> int:
        cur = self.con.execute("SELECT COUNT(1) FROM trades WHERE state IN ('pending','partial')")
        (n,) = cur.fetchone() or (0,)
        return int(n)

    # ---------- FSM-транзишены ----------

    def record_exchange_update(
        self,
        *,
        order_id: str,
        exchange_status: Optional[str],
        filled: Optional[float],
        average_price: Optional[float],
        fee_amt: float = 0.0,
        fee_ccy: str = "USDT"
    ) -> str:
        """
        Применяет апдейт с биржи и переводит состояние согласно правилам.
        Возвращает новое состояние: 'pending'|'partial'|'filled'|'canceled'|'rejected'
        """
        now = int(time.time())
        row = self.get_by_order_id(order_id)
        if not row:
            # защита от гонок: создадим запись best-effort
            with self.con:
                self.con.execute(
                    "INSERT OR IGNORE INTO trades(ts, symbol, side, price, qty, pnl, order_id, state, exp_qty, last_exchange_status, last_update_ts) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (now, "UNKNOWN/UNKNOWN", "buy", float(average_price or 0.0), float(filled or 0.0), 0.0,
                     order_id, "pending", float(filled or 0.0), str(exchange_status or ""), now)
                )
            row = self.get_by_order_id(order_id)

        cur_state = (row.get("state") or "pending").lower()
        if cur_state in _TERMINAL:
            return cur_state

        exp_qty = float(row.get("exp_qty") or 0.0)
        have_filled = max(0.0, float(filled or 0.0))
        avg_px = float(average_price or row.get("price") or 0.0)

        # нормализуем биржевой статус
        st = (exchange_status or "").strip().lower()
        is_canceled = st in {"canceled", "cancelled"}
        is_rejected = st in {"rejected"}
        is_filled   = st in {"closed", "filled", "done", "ok"} or (exp_qty > 0 and have_filled >= exp_qty)
        is_partial  = not is_filled and not is_canceled and not is_rejected and have_filled > 0.0

        new_state = cur_state
        if is_rejected:
            new_state = "rejected"
        elif is_canceled:
            new_state = "canceled"
        elif is_filled:
            new_state = "filled"
        elif is_partial:
            new_state = "partial"
        else:
            new_state = "pending"

        with self.con:
            # qty — это «исполнено на текущий момент»
            self.con.execute(
                "UPDATE trades SET state=?, qty=?, price=?, fee_amt=?, fee_ccy=?, last_exchange_status=?, last_update_ts=? "
                "WHERE order_id=?",
                (new_state, have_filled, avg_px, float(fee_amt or 0.0), fee_ccy, st or None, now, order_id)
            )
        return new_state

    # ---------- Прежние точечные операции (оставлены для совместимости) ----------

    def update_order_state(self, *, order_id: str, state: str) -> None:
        if state not in {"pending","partial","filled","canceled","rejected"}:
            state = "pending"
        with self.con:
            self.con.execute("UPDATE trades SET state=? WHERE order_id=?", (state, order_id,))

    def fill_order(self, *, order_id: str, executed_price: float, executed_qty: float, fee_amt: float = 0.0, fee_ccy: str = "USDT") -> None:
        with self.con:
            self.con.execute(
                "UPDATE trades SET state='filled', price=?, qty=?, fee_amt=?, fee_ccy=?, last_exchange_status='filled', last_update_ts=? WHERE order_id=?",
                (float(executed_price), float(executed_qty), float(fee_amt), fee_ccy, int(time.time()), order_id)
            )

    def cancel_order(self, *, order_id: str) -> None:
        with self.con:
            self.con.execute(
                "UPDATE trades SET state='canceled', last_exchange_status='canceled', last_update_ts=? WHERE order_id=?",
                (int(time.time()), order_id)
            )

    def reject_order(self, *, order_id: str) -> None:
        with self.con:
            self.con.execute(
                "UPDATE trades SET state='rejected', last_exchange_status='rejected', last_update_ts=? WHERE order_id=?",
                (int(time.time()), order_id)
            )
