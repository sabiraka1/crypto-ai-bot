# src/crypto_ai_bot/core/storage/sqlite_adapter.py
from __future__ import annotations

import sqlite3
import time
from typing import Any, Iterable, Optional, Sequence, Tuple, Dict


# -------------------------
# PRAGMAS / CONNECT
# -------------------------

def apply_connection_pragmas(conn: sqlite3.Connection) -> sqlite3.Connection:
    """
    Безопасные/полезные PRAGMA для прод-процесса бота.
    """
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute("PRAGMA temp_store=MEMORY;")
        cur.execute("PRAGMA busy_timeout=5000;")  # 5s
    finally:
        cur.close()
    return conn


def connect(db_path: str, *, detect_types: int = sqlite3.PARSE_DECLTYPES) -> sqlite3.Connection:
    """
    Единая точка подключения (автокоммит) + row_factory = dict.
    """
    conn = sqlite3.connect(
        db_path,
        timeout=5.0,
        isolation_level=None,  # autocommit
        detect_types=detect_types,
        check_same_thread=False,
    )
    conn.row_factory = _dict_factory
    return apply_connection_pragmas(conn)


def _dict_factory(cursor: sqlite3.Cursor, row: Sequence[Any]) -> Dict[str, Any]:
    d = {}
    for idx, col in enumerate(cursor.description or []):
        d[col[0]] = row[idx]
    return d


# -------------------------
# RETRY / EXEC HELPERS
# -------------------------

def _retry_write(fn, *args, attempts: int = 5, base_sleep: float = 0.02, **kwargs):
    """
    Универсальный ретрай для write-операций (busy/locked).
    """
    last = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            last = e
            if "locked" in msg or "busy" in msg:
                time.sleep(min(0.25, base_sleep * (2 ** i)))
                continue
            raise
    if last:
        raise last


def execute(conn: sqlite3.Connection, sql: str, params: Optional[Sequence[Any]] = None) -> sqlite3.Cursor:
    """
    Единый execute с ретраем для write.
    """
    cur = conn.cursor()
    if _is_write_sql(sql):
        return _retry_write(cur.execute, sql, params or [])
    return cur.execute(sql, params or [])


def executemany(conn: sqlite3.Connection, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
    """
    Единый executemany с ретраем для write.
    """
    cur = conn.cursor()
    if _is_write_sql(sql):
        return _retry_write(cur.executemany, sql, seq_of_params)
    return cur.executemany(sql, seq_of_params)


def _is_write_sql(sql: str) -> bool:
    head = (sql or "").lstrip().split(None, 1)
    if not head:
        return False
    op = head[0].upper()
    return op in ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "VACUUM")


# -------------------------
# METRICS SNAPSHOT
# -------------------------

def snapshot_metrics(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Лёгкий снэпшот внутренних метрик SQLite.
    """
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA page_count;")
        page_count = int(cur.fetchone()[0])
        cur.execute("PRAGMA page_size;")
        page_size = int(cur.fetchone()[0])
        cur.execute("PRAGMA freelist_count;")
        freelist_count = int(cur.fetchone()[0])
        # попытка soft checkpoint WAL
        wal = None
        try:
            cur.execute("PRAGMA wal_checkpoint(PASSIVE);")
            wal = cur.fetchall()
        except Exception:
            wal = None
    finally:
        cur.close()
    return {
        "page_count": page_count,
        "page_size": page_size,
        "freelist_count": freelist_count,
        "db_size_bytes": page_count * page_size,
        "wal": wal,
    }
