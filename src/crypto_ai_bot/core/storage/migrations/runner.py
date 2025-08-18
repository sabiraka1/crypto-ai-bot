# src/crypto_ai_bot/core/storage/migrations/runner.py
import sqlite3
from typing import Iterable, Tuple


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def _ensure_table(con: sqlite3.Connection, table: str, create_sql: str) -> None:
    if not _table_exists(con, table):
        con.executescript(create_sql)


def _get_columns(con: sqlite3.Connection, table: str) -> set[str]:
    cols = set()
    try:
        cur = con.execute(f"PRAGMA table_info({table});")
        for row in cur.fetchall():
            cols.add(row[1])
    except sqlite3.OperationalError:
        pass
    return cols


def _ensure_columns(
    con: sqlite3.Connection,
    table: str,
    cols_to_add: Iterable[Tuple[str, str, str | None]]
) -> None:
    existing = _get_columns(con, table)
    for name, sql_type, default in cols_to_add:
        if name in existing:
            continue
        ddl = f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"
        if default is not None:
            if isinstance(default, (int, float)) or str(default).lstrip("-").replace(".", "", 1).isdigit():
                ddl += f" DEFAULT {default}"
            else:
                ddl += f" DEFAULT '{default}'"
        con.execute(ddl)


def apply_all(con: sqlite3.Connection) -> None:
    """
    Единый, безопасный мигратор (идемпотентно):
    - создаёт недостающие таблицы
    - добавляет недостающие колонки
    - расставляет индексы
    """
    with con:
        # trades
        _ensure_table(
            con,
            "trades",
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,      -- 'buy' | 'sell'
                price REAL NOT NULL,     -- фактическая или ожидаемая цена
                qty REAL NOT NULL,       -- фактическое ИЛИ текущее исполненное количество
                pnl REAL DEFAULT 0.0
            );
            """
        )
        _ensure_columns(
            con,
            "trades",
            [
                ("order_id", "TEXT", None),
                ("state", "TEXT", "filled"),                 # pending|partial|filled|canceled|rejected
                ("fee_amt", "REAL", 0.0),
                ("fee_ccy", "TEXT", "USDT"),
                ("exp_qty", "REAL", None),                   # ожидаемое количество (для частичных)
                ("last_exchange_status", "TEXT", None),      # сырой статус от биржи
                ("last_update_ts", "INTEGER", None),         # последний апдейт из reconcile
            ],
        )

        # idempotency
        _ensure_table(
            con,
            "idempotency",
            """
            CREATE TABLE IF NOT EXISTS idempotency(
                key TEXT PRIMARY KEY,
                created_ms INTEGER NOT NULL,
                committed INTEGER NOT NULL DEFAULT 0,
                state TEXT
            );
            """
        )

        # protective_exits
        _ensure_table(
            con,
            "protective_exits",
            """
            CREATE TABLE IF NOT EXISTS protective_exits (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              position_id INTEGER,
              symbol TEXT NOT NULL,
              side TEXT NOT NULL,        -- 'sell'
              kind TEXT NOT NULL,        -- 'sl' | 'tp'
              trigger_px REAL NOT NULL,
              created_ts INTEGER NOT NULL,
              active INTEGER NOT NULL DEFAULT 1
            );
            """
        )

        # audit_log
        _ensure_table(
            con,
            "audit_log",
            """
            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts INTEGER NOT NULL,
              kind TEXT NOT NULL,
              payload TEXT
            );
            """
        )

        # индексы
        con.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_trades_state ON trades(state);")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_protective_exits_symbol ON protective_exits(symbol);")
