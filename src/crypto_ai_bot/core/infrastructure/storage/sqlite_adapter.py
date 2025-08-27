## `core/storage/sqlite_adapter.py`
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from typing import Iterator
def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)  # autocommit; BEGIN вручную
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn
@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    """BEGIN IMMEDIATE (write txn) + COMMIT/ROLLBACK. Возвращает курсор.
    Используем явные транзакции для атомарности операций (например, идемпотентность).
    """
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE;")
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()