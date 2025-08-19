# src/crypto_ai_bot/core/storage/sqlite_adapter.py
from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Optional, Sequence, Tuple, Dict

# -------------------------
# PRAGMAS / CONNECT
# -------------------------

def apply_connection_pragmas(conn: sqlite3.Connection) -> sqlite3.Connection:
    """
    Безопасные/полезные PRAGMA для прод-процесса бота.
    Можно вызывать сразу после connect().
    """
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA temp_store=MEMORY;")
        cur.execute("PRAGMA mmap_size=268435456;")  # 256 MiB
        cur.execute("PRAGMA busy_timeout=5000;")
        cur.execute("PRAGMA foreign_keys=ON;")
    finally:
        cur.close()
    return conn


def connect(path: str) -> sqlite3.Connection:
    # Ensure directory exists
    import os
    db_dir = os.path.dirname(path)
    if db_dir and db_dir != '.':
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return apply_connection_pragmas(conn)

# -------------------------
# EXEC HELPERS
# -------------------------

def execute(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur
    except sqlite3.OperationalError:
        # лёгкий повтор при «database is locked»
        conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
        cur.execute(sql, params)
        return cur
    finally:
        # не закрываем cur — отдаём его вызывающему, он сам .close()
        ...

def executemany(conn: sqlite3.Connection, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
    cur = conn.cursor()
    try:
        cur.executemany(sql, seq_of_params)
        return cur
    except sqlite3.OperationalError:
        conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
        cur.executemany(sql, seq_of_params)
        return cur
    finally:
        ...

# -------------------------
# METRICS SNAPSHOT
# -------------------------

def snapshot_metrics(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Используется maintenance/health для быстрой телеметрии БД.
    """
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA page_count;")
        page_count = cur.fetchone()[0]
        cur.execute("PRAGMA page_size;")
        page_size = cur.fetchone()[0]
        cur.execute("PRAGMA freelist_count;")
        freelist_count = cur.fetchone()[0]
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
