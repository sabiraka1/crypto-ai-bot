from __future__ import annotations
import os
import sqlite3
from typing import Iterable

SCHEMA_SQL = """PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT PRIMARY KEY,
  expires_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
  id TEXT PRIMARY KEY,
  client_order_id TEXT,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,      -- 'buy' | 'sell'
  type TEXT NOT NULL,      -- 'market' | 'limit' | ...
  amount REAL NOT NULL,    -- base amount (signed: buy > 0, sell < 0 for convenience)
  price REAL NOT NULL,     -- executed avg price
  status TEXT NOT NULL,    -- 'open' | 'closed' | 'canceled'
  ts_ms INTEGER NOT NULL   -- execution time
);

CREATE INDEX IF NOT EXISTS ix_trades_symbol_ts ON trades(symbol, ts_ms);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event TEXT NOT NULL,
  details TEXT,
  ts_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ohlcv (
  symbol TEXT NOT NULL,
  ts_ms INTEGER NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  PRIMARY KEY(symbol, ts_ms)
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    # Apply base schema (idempotent)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
