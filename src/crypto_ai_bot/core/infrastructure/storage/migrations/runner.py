from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
import shutil
import sqlite3


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _backup_file(src: str, *, dest_dir: str, now_ms: int) -> str | None:
    if not src or not os.path.exists(src):
        return None
    _ensure_dir(dest_dir)
    base = os.path.basename(src)
    dst = os.path.join(dest_dir, f"{now_ms}_{base}")
    shutil.copy2(src, dst)
    return dst


@dataclass(frozen=True)
class PyMigration:
    version: int
    name: str
    up: Callable[[sqlite3.Connection], None]


def _apply_sql(conn: sqlite3.Connection, sql: str) -> None:
    if not sql.strip():
        return
    with conn:
        conn.executescript(sql)


def _init_schema_table(conn: sqlite3.Connection) -> None:
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
    cur = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version;")
    row = cur.fetchone()
    return int(row[0] or 0)


def _mark_applied(conn: sqlite3.Connection, version: int, name: str, now_ms: int) -> None:
    with conn:
        conn.execute(
            "INSERT INTO schema_version(version, name, applied_at) VALUES (?, ?, ?);",
            (version, name, now_ms),
        )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table});")
    return any(row[1] == column for row in cur.fetchall())


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if not _column_exists(conn, table, column):
        with conn:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl};")


def _pymigrations() -> list[PyMigration]:
    migs: list[PyMigration] = []

    # V0001 Гўв‚¬вЂќ ДћВ±ДћВ°ДћВ·ДћВѕДћВІДћВ°Г‘ВЏ Г‘ВЃГ‘вЂ¦ДћВµДћВјДћВ°
    def _v1(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
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
            CREATE TABLE IF NOT EXISTS positions (
                symbol            TEXT PRIMARY KEY,
                base_qty          TEXT NOT NULL,
                avg_price         TEXT NOT NULL,
                updated_ms        INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS idempotency (
                key               TEXT PRIMARY KEY,
                ts_ms             INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                topic             TEXT NOT NULL,
                payload_json      TEXT NOT NULL,
                ts_ms             INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS market_data (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol            TEXT NOT NULL,
                bid               TEXT,
                ask               TEXT,
                last              TEXT,
                ts_ms             INTEGER NOT NULL
            );
            """,
        )

    migs.append(PyMigration(1, "init", _v1))

    # V0002 - ДћВґДћВѕДћВ±ДћВ°ДћВІДћВёДћВј broker_order_id ДћВё client_order_id
    def _v2(conn: sqlite3.Connection) -> None:
        _add_column_if_missing(conn, "trades", "broker_order_id", "TEXT")
        _add_column_if_missing(conn, "trades", "client_order_id", "TEXT")
        _add_column_if_missing(conn, "trades", "filled", "TEXT")

    migs.append(PyMigration(2, "trades_order_ids", _v2))

    # V0006 Гўв‚¬вЂќ ДћВёДћВЅДћВґДћВµДћВєГ‘ВЃГ‘вЂ№ ДћВїДћВѕ Г‘ВЃДћВґДћВµДћВ»ДћВєДћВ°ДћВј
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
            """,
        )

    migs.append(PyMigration(6, "trades_indexes", _v6))

    # V0007 Гўв‚¬вЂќ Г‘Ж’ДћВЅДћВёДћВєДћВ°ДћВ»Г‘Е’ДћВЅДћВѕГ‘ВЃГ‘вЂљГ‘Е’ ДћВёДћВґДћВµДћВјДћВїДћВѕГ‘вЂљДћВµДћВЅГ‘вЂљДћВЅДћВѕГ‘ВЃГ‘вЂљДћВё
    def _v7(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_idempotency_key
                ON idempotency(key);
            CREATE INDEX IF NOT EXISTS idx_idempotency_ts
                ON idempotency(ts_ms);
            """,
        )

    migs.append(PyMigration(7, "idempotency_unique_and_ts", _v7))

    # V0008 Гўв‚¬вЂќ ДћВёДћВЅДћВґДћВµДћВєГ‘ВЃ ДћВїДћВѕДћВ·ДћВёГ‘вЂ ДћВёДћВ№
    def _v8(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_positions_symbol
                ON positions(symbol);
            """,
        )

    migs.append(PyMigration(8, "positions_idx", _v8))

    # V0010 Гўв‚¬вЂќ ДћВёДћВЅДћВґДћВµДћВєГ‘ВЃ ДћВ°Г‘Ж’ДћВґДћВёГ‘вЂљДћВ°
    def _v10(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_audit_ts
                ON audit(ts_ms);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_trades_broker_order_id
                ON trades(broker_order_id)
                WHERE broker_order_id IS NOT NULL;
            """,
        )

    migs.append(PyMigration(10, "audit_ts_idx", _v10))

    # V0011 Гўв‚¬вЂќ Г‘в‚¬ДћВ°Г‘ВЃГ‘Л†ДћВёГ‘в‚¬ДћВµДћВЅДћВёДћВµ Г‘ВЃГ‘вЂ¦ДћВµДћВјГ‘вЂ№
    def _v11(conn: sqlite3.Connection) -> None:
        _add_column_if_missing(conn, "positions", "avg_entry_price", "TEXT NOT NULL DEFAULT '0'")
        _add_column_if_missing(conn, "positions", "realized_pnl", "TEXT NOT NULL DEFAULT '0'")
        _add_column_if_missing(conn, "positions", "unrealized_pnl", "TEXT NOT NULL DEFAULT '0'")
        _add_column_if_missing(conn, "positions", "updated_ts_ms", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "positions", "version", "INTEGER NOT NULL DEFAULT 0")

        try:
            with conn:
                conn.execute(
                    "UPDATE positions SET avg_entry_price = COALESCE(avg_entry_price, avg_price, '0')"
                )
        except Exception:
            pass
        try:
            with conn:
                conn.execute("UPDATE positions SET updated_ts_ms = COALESCE(updated_ts_ms, updated_ms, 0)")
        except Exception:
            pass

    migs.append(PyMigration(11, "positions_schema_extend", _v11))

    # V0012 - orders table
    def _v12(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker_order_id TEXT,
                client_order_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                amount TEXT NOT NULL,
                filled TEXT NOT NULL DEFAULT '0',
                status TEXT NOT NULL DEFAULT 'open',
                ts_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            """,
        )

    migs.append(PyMigration(12, "orders_table", _v12))

    return migs


def run_migrations(
    conn: sqlite3.Connection,
    *,
    now_ms: int,
    db_path: str,
    do_backup: bool = True,
    backup_retention_days: int = 30,
) -> None:
    """ДћЕёГ‘в‚¬ДћВёДћВјДћВµДћВЅГ‘ВЏДћВµГ‘вЂљ ДћВїГ‘в‚¬ДћВѕДћВіГ‘в‚¬ДћВ°ДћВјДћВјДћВЅГ‘вЂ№ДћВµ ДћВјДћВёДћВіГ‘в‚¬ДћВ°Г‘вЂ ДћВёДћВё."""
    assert isinstance(now_ms, int), "now_ms must be int (epoch ms)"
    _init_schema_table(conn)

    if do_backup and db_path:
        dest = os.path.join(os.path.dirname(db_path) or ".", "backups")
        _backup_file(db_path, dest_dir=dest, now_ms=now_ms)

    current = _current_version(conn)
    for mig in sorted(_pymigrations(), key=lambda m: m.version):
        if mig.version <= current:
            continue
        mig.up(conn)
        _mark_applied(conn, mig.version, mig.name, now_ms)

    # ДћЕёДћВѕДћВґГ‘вЂЎДћВёГ‘ВЃГ‘вЂљДћВёГ‘вЂљГ‘Е’ Г‘ВЃГ‘вЂљДћВ°Г‘в‚¬Г‘вЂ№ДћВµ ДћВ±Г‘ВЌДћВєДћВ°ДћВїГ‘вЂ№
    try:
        if do_backup and db_path and backup_retention_days >= 0:
            dest = os.path.join(os.path.dirname(db_path) or ".", "backups")
            if os.path.isdir(dest):
                files = sorted(
                    (os.path.join(dest, f) for f in os.listdir(dest)),
                    key=lambda p: os.path.getmtime(p),
                    reverse=True,
                )
                keep = max(3, int(backup_retention_days / 7))
                for p in files[keep:]:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
    except Exception:
        pass
