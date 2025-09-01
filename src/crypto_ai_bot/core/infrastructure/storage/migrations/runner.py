from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass


# Лёгкие утилиты (без жёстких зависимостей)
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


# -------------------------
# Программные миграции (источник истины)
# -------------------------
def _pymigrations() -> list[PyMigration]:
    migs: list[PyMigration] = []

    # V0001 — базовая схема (если у вас уже была, оператор IF NOT EXISTS всё равно безопасен)
    def _v1(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE TABLE IF NOT EXISTS trades (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol            TEXT NOT NULL,
                side              TEXT NOT NULL,
                amount            TEXT NOT NULL,     -- Decimal в текстовом виде
                price             TEXT NOT NULL,
                cost              TEXT NOT NULL,
                fee_quote         TEXT,
                client_order_id   TEXT,
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

    # V0006 — индексы по сделкам
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

    # V0007 — уникальность идемпотентности + ускорение GC
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

    # V0008 — индекс позиций
    def _v8(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_positions_symbol
                ON positions(symbol);
            """,
        )

    migs.append(PyMigration(8, "positions_idx", _v8))

    # V0010 — индекс аудита по времени
    def _v10(conn: sqlite3.Connection) -> None:
        _apply_sql(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_audit_ts
                ON audit(ts_ms);
            """,
        )

    migs.append(PyMigration(10, "audit_ts_idx", _v10))

    

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table});")
    return any(row[1] == column for row in cur.fetchall())

def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if not _column_exists(conn, table, column):
        with conn:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl};")

def _rename_column_if_exists(conn: sqlite3.Connection, table: str, old: str, new: str) -> None:
    # SQLite нет IF EXISTS для rename колонок — обойдёмся копированием данных на уровне UPDATE
    pass  # используем UPDATE-перенос ниже



# V0011 — расширение схемы для совместимости с репозиториями
def _v11(conn: sqlite3.Connection) -> None:
    # trades: добавить недостающие колонки
    _add_column_if_missing(conn, "trades", "broker_order_id", "TEXT")
    _add_column_if_missing(conn, "trades", "filled", "TEXT")

    # positions: добавить новые поля
    _add_column_if_missing(conn, "positions", "avg_entry_price", "TEXT NOT NULL DEFAULT '0'")
    _add_column_if_missing(conn, "positions", "realized_pnl", "TEXT NOT NULL DEFAULT '0'")
    _add_column_if_missing(conn, "positions", "unrealized_pnl", "TEXT NOT NULL DEFAULT '0'")
    _add_column_if_missing(conn, "positions", "updated_ts_ms", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "positions", "version", "INTEGER NOT NULL DEFAULT 0")

    # совместимость имён: перенести avg_price -> avg_entry_price; updated_ms -> updated_ts_ms
    try:
        with conn:
            conn.execute("UPDATE positions SET avg_entry_price = COALESCE(avg_entry_price, avg_price, '0')")
    except Exception:
        pass
    try:
        with conn:
            conn.execute("UPDATE positions SET updated_ts_ms = COALESCE(updated_ts_ms, updated_ms, 0)")
    except Exception:
        pass

migs.append(PyMigration(11, "positions_schema_extend", _v11))

    return migs


# -------------------------
# Публичный раннер
# -------------------------
def run_migrations(
    conn: sqlite3.Connection,
    *,
    now_ms: int,
    db_path: str,
    do_backup: bool = True,
    backup_retention_days: int = 30,
) -> None:
    """
    Применяет программные миграции (Python) как единственный источник истины.
    SQL-файлы, лежащие в репозитории, считаются архивом и НЕ исполняются.
    """
    assert isinstance(now_ms, int), "now_ms must be int (epoch ms)"
    _init_schema_table(conn)

    # Бэкап перед миграциями (безопасно для WAL)
    if do_backup and db_path:
        dest = os.path.join(os.path.dirname(db_path) or ".", "backups")
        _backup_file(db_path, dest_dir=dest, now_ms=now_ms)

    current = _current_version(conn)
    for mig in sorted(_pymigrations(), key=lambda m: m.version):
        if mig.version <= current:
            continue
        mig.up(conn)
        _mark_applied(conn, mig.version, mig.name, now_ms)

    # Подчистить старые бэкапы (best-effort)
    try:
        if do_backup and db_path and backup_retention_days >= 0:
            dest = os.path.join(os.path.dirname(db_path) or ".", "backups")
            if os.path.isdir(dest):
                # оставим N последних по времени
                files = sorted(
                    (os.path.join(dest, f) for f in os.listdir(dest)),
                    key=lambda p: os.path.getmtime(p),
                    reverse=True,
                )
                keep = max(3, int(backup_retention_days / 7))  # эвристика
                for p in files[keep:]:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
    except Exception:
        pass
