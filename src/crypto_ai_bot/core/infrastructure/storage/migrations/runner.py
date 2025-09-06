"""
Database migrations runner for crypto-ai-bot.

Manages schema versioning and migrations with safe online SQLite backups.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Iterable

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)


# --------------------- filesystem helpers ---------------------

def _ensure_dir(path: str | Path) -> None:
    """Ensure directory exists."""
    Path(path).mkdir(parents=True, exist_ok=True)


def _atomic_replace(tmp: Path, dst: Path) -> None:
    """Atomically move file into place (replace if exists)."""
    _ensure_dir(dst.parent)
    os.replace(str(tmp), str(dst))


# --------------------- backup helpers ---------------------

def _sqlite_online_backup(src_db: Path, dst_file: Path) -> None:
    """
    Create a consistent SQLite backup using the online backup API.

    Writes to a temporary file first, then atomically replaces into dst_file.
    """
    tmp_fd, tmp_path_str = tempfile.mkstemp(prefix=dst_file.stem + "_", suffix=dst_file.suffix, dir=str(dst_file.parent))
    os.close(tmp_fd)
    tmp_path = Path(tmp_path_str)

    try:
        src_conn = sqlite3.connect(str(src_db), timeout=30, isolation_level=None)
        try:
            dst_conn = sqlite3.connect(str(tmp_path), timeout=30, isolation_level=None)
            try:
                src_conn.backup(dst_conn)  # copy entire DB in a consistent way
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

        _atomic_replace(tmp_path, dst_file)
        try:
            os.chmod(dst_file, 0o600)
        except Exception:
            pass
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _backup_file(db_path: str, *, dest_dir: str, now_ms: int) -> Optional[str]:
    """
    Create backup of SQLite file using online backup API.

    Returns absolute path to created backup or None if source missing.
    """
    if not db_path:
        return None

    src = Path(db_path)
    if not src.exists():
        return None

    dest_root = Path(dest_dir)
    _ensure_dir(dest_root)

    # backup name: <name>_<epoch_ms>.sqlite3
    stem = src.stem
    dst = dest_root / f"{stem}_{now_ms}.sqlite3"

    try:
        _sqlite_online_backup(src, dst)
        return str(dst.resolve())
    except Exception as e:
        _log.warning("backup_failed", extra={"src": str(src), "dst": str(dst), "error": str(e)})
        # fallback: attempt best-effort copy (may be inconsistent under write load)
        try:
            shutil.copy2(str(src), str(dst))
            return str(dst.resolve())
        except Exception as e2:
            _log.error("backup_copy_failed", extra={"src": str(src), "dst": str(dst), "error": str(e2)})
            return None


def _cleanup_backups(dest_dir: str, *, retention_days: int) -> None:
    """
    Cleanup old backups in dest_dir:
    - remove files older than retention_days (if >=0),
    - always keep at least 3 most-recent files even if older.
    """
    try:
        root = Path(dest_dir)
        if not root.is_dir():
            return

        files = sorted(
            (p for p in root.iterdir() if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return

        # Always keep top 3 newest
        keep_safety = set(files[:3])

        if retention_days >= 0:
            import time
            cutoff = time.time() - (retention_days * 24 * 60 * 60)
            for p in files[3:]:
                # delete only if older than cutoff
                if p.stat().st_mtime < cutoff:
                    try:
                        p.unlink()
                        _log.debug("Removed old backup", extra={"path": str(p)})
                    except Exception:
                        pass
        # else: negative retention -> do nothing beyond safety keep
    except Exception as e:
        _log.warning("backup_cleanup_failed", extra={"error": str(e), "dir": dest_dir})


# --------------------- schema helpers ---------------------

@dataclass(frozen=True)
class PyMigration:
    """Python migration definition."""
    version: int
    name: str
    up: Callable[[sqlite3.Connection], None]


def _apply_sql(conn: sqlite3.Connection, sql: str) -> None:
    """Apply SQL script (no-op on empty)."""
    if not sql or not sql.strip():
        return
    with conn:
        conn.executescript(sql)


def _init_schema_table(conn: sqlite3.Connection) -> None:
    """Initialize schema version table."""
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version     INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                applied_at  INTEGER NOT NULL
            );
            """
        )


def _current_version(conn: sqlite3.Connection) -> int:
    """Get current schema version."""
    cur = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version;")
    row = cur.fetchone()
    return int(row[0] or 0)


def _mark_applied(conn: sqlite3.Connection, version: int, name: str, now_ms: int) -> None:
    """Mark migration as applied."""
    with conn:
        conn.execute(
            "INSERT INTO schema_version(version, name, applied_at) VALUES (?, ?, ?);",
            (version, name, now_ms),
        )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Check if table exists."""
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1;",
        (table,),
    )
    return cur.fetchone() is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if column exists in table."""
    cur = conn.execute(f"PRAGMA table_info({table});")
    return any(row[1] == column for row in cur.fetchall())


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Add column if it doesn't exist."""
    if not _column_exists(conn, table, column):
        with conn:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl};")


# --------------------- migrations list ---------------------

def _pymigrations() -> list[PyMigration]:
    """Get all Python migrations (idempotent)."""
    migs: list[PyMigration] = []

    # V0001 - Base schema
    def _v1(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            -- Trades table
            CREATE TABLE IF NOT EXISTS trades (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol            TEXT NOT NULL,
                side              TEXT NOT NULL,
                amount            TEXT NOT NULL,
                price             TEXT NOT NULL,
                cost              TEXT NOT NULL,
                fee_quote         TEXT,
                ts_ms             INTEGER NOT NULL
            );

            -- Positions table
            CREATE TABLE IF NOT EXISTS positions (
                symbol            TEXT PRIMARY KEY,
                base_qty          TEXT NOT NULL,
                avg_price         TEXT NOT NULL,
                updated_ms        INTEGER NOT NULL
            );

            -- Idempotency table
            CREATE TABLE IF NOT EXISTS idempotency (
                key               TEXT PRIMARY KEY,
                ts_ms             INTEGER NOT NULL
            );

            -- Audit table
            CREATE TABLE IF NOT EXISTS audit (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                topic             TEXT NOT NULL,
                payload_json      TEXT NOT NULL,
                ts_ms             INTEGER NOT NULL
            );

            -- Market data table
            CREATE TABLE IF NOT EXISTS market_data (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol            TEXT NOT NULL,
                bid               TEXT,
                ask               TEXT,
                last              TEXT,
                ts_ms             INTEGER NOT NULL
            );

            -- Risk counters table
            CREATE TABLE IF NOT EXISTS risk_counters (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                rule              TEXT NOT NULL,
                symbol            TEXT NOT NULL,
                value             TEXT NOT NULL,
                ts_ms             INTEGER NOT NULL
            );
            """
        )

    migs.append(PyMigration(1, "init", _v1))

    # V0002 - Add order tracking columns
    def _v2(conn: sqlite3.Connection) -> None:
        _add_column_if_missing(conn, "trades", "broker_order_id", "TEXT")
        _add_column_if_missing(conn, "trades", "client_order_id", "TEXT")
        _add_column_if_missing(conn, "trades", "filled", "TEXT")

    migs.append(PyMigration(2, "trades_order_ids", _v2))

    # V0003 - Add trace_id for correlation
    def _v3(conn: sqlite3.Connection) -> None:
        _add_column_if_missing(conn, "trades", "trace_id", "TEXT")
        _add_column_if_missing(conn, "audit", "trace_id", "TEXT")
        _add_column_if_missing(conn, "risk_counters", "trace_id", "TEXT")

    migs.append(PyMigration(3, "add_trace_id", _v3))

    # V0004 - Add status columns
    def _v4(conn: sqlite3.Connection) -> None:
        _add_column_if_missing(conn, "trades", "status", "TEXT DEFAULT 'completed'")
        _add_column_if_missing(conn, "positions", "status", "TEXT DEFAULT 'open'")

    migs.append(PyMigration(4, "add_status", _v4))

    # V0005 - Add metadata columns
    def _v5(conn: sqlite3.Connection) -> None:
        _add_column_if_missing(conn, "trades", "metadata_json", "TEXT")
        _add_column_if_missing(conn, "positions", "metadata_json", "TEXT")

    migs.append(PyMigration(5, "add_metadata", _v5))

    # V0006 - Indexes for performance
    def _v6(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts
                ON trades(symbol, ts_ms);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_trades_client_order_id
                ON trades(client_order_id)
                WHERE client_order_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_trades_ts
                ON trades(ts_ms);
            CREATE INDEX IF NOT EXISTS idx_trades_trace_id
                ON trades(trace_id)
                WHERE trace_id IS NOT NULL;
            """
        )

    migs.append(PyMigration(6, "trades_indexes", _v6))

    # V0007 - Idempotency improvements
    def _v7(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_idempotency_key
                ON idempotency(key);
            CREATE INDEX IF NOT EXISTS idx_idempotency_ts
                ON idempotency(ts_ms);
            """
        )

    migs.append(PyMigration(7, "idempotency_unique_and_ts", _v7))

    # V0008 - Position indexes
    def _v8(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_positions_symbol
                ON positions(symbol);
            CREATE INDEX IF NOT EXISTS idx_positions_status
                ON positions(status);
            """
        )

    migs.append(PyMigration(8, "positions_idx", _v8))

    # V0009 - Risk counter indexes
    def _v9(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_risk_counters_rule_symbol
                ON risk_counters(rule, symbol);
            CREATE INDEX IF NOT EXISTS idx_risk_counters_ts
                ON risk_counters(ts_ms);
            """
        )

    migs.append(PyMigration(9, "risk_counters_idx", _v9))

    # V0010 - Audit indexes
    def _v10(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_audit_ts
                ON audit(ts_ms);
            CREATE INDEX IF NOT EXISTS idx_audit_topic
                ON audit(topic);
            CREATE INDEX IF NOT EXISTS idx_audit_trace_id
                ON audit(trace_id)
                WHERE trace_id IS NOT NULL;
            """
        )

    migs.append(PyMigration(10, "audit_idx", _v10))

    # V0011 - Extended position tracking
    def _v11(conn: sqlite3.Connection) -> None:
        _add_column_if_missing(conn, "positions", "avg_entry_price", "TEXT NOT NULL DEFAULT '0'")
        _add_column_if_missing(conn, "positions", "realized_pnl", "TEXT NOT NULL DEFAULT '0'")
        _add_column_if_missing(conn, "positions", "unrealized_pnl", "TEXT NOT NULL DEFAULT '0'")
        _add_column_if_missing(conn, "positions", "updated_ts_ms", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "positions", "version", "INTEGER NOT NULL DEFAULT 0")

        # Migrate existing data (best effort)
        try:
            with conn:
                conn.execute(
                    "UPDATE positions SET avg_entry_price = COALESCE(avg_entry_price, avg_price, '0')"
                )
                conn.execute(
                    "UPDATE positions SET updated_ts_ms = COALESCE(updated_ts_ms, updated_ms, 0)"
                )
        except Exception:
            pass

    migs.append(PyMigration(11, "positions_extended", _v11))

    # V0012 - Orders table
    def _v12(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE TABLE IF NOT EXISTS orders (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                broker_order_id   TEXT,
                client_order_id   TEXT,
                symbol            TEXT NOT NULL,
                side              TEXT NOT NULL,
                type              TEXT NOT NULL DEFAULT 'market',
                amount            TEXT NOT NULL,
                price             TEXT,
                filled            TEXT NOT NULL DEFAULT '0',
                status            TEXT NOT NULL DEFAULT 'open',
                trace_id          TEXT,
                metadata_json     TEXT,
                ts_ms             INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_client_order_id
                ON orders(client_order_id)
                WHERE client_order_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_orders_trace_id
                ON orders(trace_id)
                WHERE trace_id IS NOT NULL;
            """
        )

    migs.append(PyMigration(12, "orders_table", _v12))

    # V0013 - Idempotency expiration
    def _v13(conn: sqlite3.Connection) -> None:
        _add_column_if_missing(conn, "idempotency", "expire_at", "INTEGER NOT NULL DEFAULT 0")
        _apply_sql(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_idempotency_expire
                ON idempotency(expire_at);
            """
        )

    migs.append(PyMigration(13, "idempotency_expire", _v13))

    # V0014 - Protective exits tracking
    def _v14(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE TABLE IF NOT EXISTS protective_exits (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol            TEXT NOT NULL,
                position_id       TEXT NOT NULL,
                exit_type         TEXT NOT NULL,
                trigger_price     TEXT,
                exit_price        TEXT,
                amount            TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'pending',
                trace_id          TEXT,
                ts_ms             INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_protective_exits_symbol
                ON protective_exits(symbol);
            CREATE INDEX IF NOT EXISTS idx_protective_exits_status
                ON protective_exits(status);
            """
        )

    migs.append(PyMigration(14, "protective_exits", _v14))

    return migs


# --------------------- public API ---------------------

def run_migrations(
    conn: sqlite3.Connection,
    *,
    now_ms: int,
    db_path: str,
    do_backup: bool = True,
    backup_retention_days: int = 30,
) -> None:
    """
    Run all pending migrations.

    Args:
        conn: SQLite connection
        now_ms: Current timestamp in milliseconds
        db_path: Path to database file
        do_backup: Create backup before migration
        backup_retention_days: Days to keep backups (always keep ≥3 latest)
    """
    assert isinstance(now_ms, int), "now_ms must be int (epoch ms)"

    _init_schema_table(conn)

    # Create backup if requested
    if do_backup and db_path:
        dest = os.path.join(os.path.dirname(db_path) or ".", "backups")
        backup_path = _backup_file(db_path, dest_dir=dest, now_ms=now_ms)
        if backup_path:
            _log.info("Created backup", extra={"path": backup_path})

    # Get current version
    current = _current_version(conn)
    _log.info("Current schema version", extra={"version": current})

    # Apply pending migrations
    applied = 0
    for mig in sorted(_pymigrations(), key=lambda m: m.version):
        if mig.version <= current:
            continue

        _log.info("Applying migration", extra={"version": mig.version, "name": mig.name})
        mig.up(conn)
        _mark_applied(conn, mig.version, mig.name, now_ms)
        applied += 1

    if applied > 0:
        _log.info("Migrations applied", extra={"count": applied})
    else:
        _log.info("No pending migrations")

    # Cleanup old backups
    if do_backup and db_path and backup_retention_days >= 0:
        dest = os.path.join(os.path.dirname(db_path) or ".", "backups")
        _cleanup_backups(dest, retention_days=int(backup_retention_days))


__all__ = [
    "PyMigration",
    "run_migrations",
]
