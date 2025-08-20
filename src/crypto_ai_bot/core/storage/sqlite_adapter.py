# src/crypto_ai_bot/core/storage/sqlite_adapter.py
from __future__ import annotations

import sqlite3
from typing import Optional, Iterable

DB_TIMEOUT_SEC = 30.0

PRAGMAS = [
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("temp_store", "MEMORY"),
    ("mmap_size", str(64 * 1024 * 1024)),
    ("cache_size", str(-64 * 1024)),  # ~64MB
]

INDICES: Iterable[str] = (
    "CREATE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id);",
    "CREATE INDEX IF NOT EXISTS idx_trades_client_order_id ON trades(client_order_id);",
    "CREATE INDEX IF NOT EXISTS idx_idempotency_key ON idempotency(key);",
    "CREATE INDEX IF NOT EXISTS idx_idempotency_exp ON idempotency(expires_ms);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);",
)

def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=DB_TIMEOUT_SEC, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn

def _apply_pragmas(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for k, v in PRAGMAS:
        cur.execute(f"PRAGMA {k}={v}")
    cur.close()

def ensure_schema(conn: sqlite3.Connection) -> None:
    # здесь оставь свои CREATE TABLE IF NOT EXISTS ...
    pass  # предполагается, что у тебя уже есть миграции

def ensure_indices(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for sql in INDICES:
        cur.execute(sql)
    cur.close()
