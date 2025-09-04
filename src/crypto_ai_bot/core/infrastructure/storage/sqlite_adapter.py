## `core/storage/sqlite_adapter.py`
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        db_path, check_same_thread=False, isolation_level=None
    )  # autocommit; BEGIN handled manually
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    """BEGIN IMMEDIATE (write txn) + COMMIT/ROLLBACK. Returns cursor.
    Use explicit transactions for atomic operations (e.g., idempotency).
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
