# src/crypto_ai_bot/core/infrastructure/storage/migrations/runner.py
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple

def _apply_pragmas(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("PRAGMA foreign_keys=ON;")
    cur.execute("PRAGMA busy_timeout=5000;")
    cur.close()

def _begin_immediate(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE;")

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (name,))
    row = cur.fetchone()
    return bool(row)

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table});")
    return any(r[1] == column for r in cur.fetchall())

def _ensure_table(conn: sqlite3.Connection, create_sql: str) -> None:
    conn.execute(create_sql)

def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_def: str) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def};")

def _ensure_index(conn: sqlite3.Connection, create_index_sql: str) -> None:
    conn.execute(create_index_sql)

# ↑ новая версия (включает fee_quote в trades)
BASELINE_VERSION = "2025-08-30-01-fee"
BASELINE_CHECKSUM = "sha256:baseline_with_fee_and_last_trade_ts"

def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations(
            version TEXT PRIMARY KEY,
            applied_at_ms INTEGER NOT NULL,
            checksum TEXT NOT NULL
        );
    """)

def _applied_versions(conn: sqlite3.Connection) -> List[str]:
    cur = conn.execute("SELECT version FROM schema_migrations ORDER BY applied_at_ms ASC;")
    return [str(r[0]) for r in cur.fetchall()]

def _record_migration(conn: sqlite3.Connection, version: str, applied_at_ms: int, checksum: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at_ms, checksum) VALUES(?,?,?);",
        (version, applied_at_ms, checksum),
    )

def _backup_sqlite(src_path: str, out_dir: str, retention_days: int = 30) -> Optional[str]:
    try:
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        base = os.path.basename(src_path)
        name = os.path.splitext(base)[0]
        out_path = os.path.join(out_dir, f"{name}-backup-{ts}.sqlite3")
        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(out_path)
        with dst:
            src.backup(dst)  # type: ignore[attr-defined]
        src.close(); dst.close()
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(retention_days))
        for f in os.listdir(out_dir):
            if not f.endswith(".sqlite3"): continue
            full = os.path.join(out_dir, f)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(full), tz=timezone.utc)
                if mtime < cutoff:
                    os.remove(full)
            except Exception:
                pass
        return out_path
    except Exception:
        return None

def _baseline(conn: sqlite3.Connection) -> None:
    _ensure_table(conn, """
        CREATE TABLE IF NOT EXISTS positions(
            symbol TEXT PRIMARY KEY,
            base_qty NUMERIC NOT NULL DEFAULT 0
        );
    """)
    _ensure_table(conn, """
        CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broker_order_id TEXT,
            client_order_id TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            amount NUMERIC NOT NULL DEFAULT 0,
            price NUMERIC NOT NULL DEFAULT 0,
            cost  NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'closed',
            ts_ms INTEGER NOT NULL,
            created_at_ms INTEGER NOT NULL
        );
    """)
    _ensure_index(conn, "CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts_ms);")
    _ensure_table(conn, """
        CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            payload TEXT,
            ts_ms INTEGER NOT NULL
        );
    """)
    _ensure_index(conn, "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts_ms);")
    _ensure_table(conn, """
        CREATE TABLE IF NOT EXISTS idempotency(
            bucket_ms INTEGER NOT NULL,
            key TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY(bucket_ms, key)
        );
    """)
    _ensure_table(conn, """
        CREATE TABLE IF NOT EXISTS market_data(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            payload TEXT NOT NULL,
            ts_ms INTEGER NOT NULL
        );
    """)
    _ensure_index(conn, "CREATE INDEX IF NOT EXISTS idx_md_symbol_ts ON market_data(symbol, ts_ms);")
    _ensure_table(conn, """
        CREATE TABLE IF NOT EXISTS instance_lock(
            app TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            expires_at_ms INTEGER NOT NULL
        );
    """)
    # доп. колонки (идемпотентно)
    for col, col_def in [
        ("avg_entry_price", "NUMERIC DEFAULT 0"),
        ("realized_pnl",   "NUMERIC DEFAULT 0"),
        ("unrealized_pnl", "NUMERIC DEFAULT 0"),
        ("opened_at",      "INTEGER DEFAULT 0"),
        ("updated_at",     "INTEGER DEFAULT 0"),
        ("last_trade_ts_ms", "INTEGER DEFAULT 0"),
    ]:
        _ensure_column(conn, "positions", col, col_def)
    # НОВОЕ: комиссии по сделкам
    _ensure_column(conn, "trades", "fee_quote", "NUMERIC DEFAULT 0")

def run_migrations(
    conn: sqlite3.Connection,
    *,
    now_ms: int,
    db_path: Optional[str] = None,
    do_backup: bool = True,
    backup_retention_days: int = 30,
) -> str:
    _apply_pragmas(conn)
    _ensure_schema_migrations(conn)
    applied = set(_applied_versions(conn))
    if BASELINE_VERSION in applied:
        return BASELINE_VERSION
    if do_backup and db_path and os.path.exists(db_path):
        out_dir = os.path.join(os.path.dirname(db_path), "backups")
        _backup_sqlite(db_path, out_dir, retention_days=backup_retention_days)
    _begin_immediate(conn)
    try:
        _baseline(conn)
        _record_migration(conn, BASELINE_VERSION, now_ms, BASELINE_CHECKSUM)
        conn.commit()
        return BASELINE_VERSION
    except Exception:
        conn.rollback()
        raise
