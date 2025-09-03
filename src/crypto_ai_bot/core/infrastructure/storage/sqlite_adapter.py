## `core/storage/sqlite_adapter.py`
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        db_path, check_same_thread=False, isolation_level=None
    )  # autocommit; BEGIN Ğ²Ñ€ÑƒÑ‡Ğ½ÑƒÑ
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    """BEGIN IMMEDIATE (write txn) + COMMIT/ROLLBACK. Ğ’Ğ¾Ğ·Ğ²Ñ€Ğ°Ñ‰Ğ°ĞµÑ‚ ĞºÑƒÑ€ÑĞ¾Ñ€.
    Ğ˜ÑĞ¿Ğ¾Ğ»ÑŒĞ·ÑƒĞµĞ¼ ÑĞ²Ğ½Ñ‹Ğµ Ñ‚Ñ€Ğ°Ğ½Ğ·Ğ°ĞºÑ†Ğ¸Ğ¸ Ğ´Ğ»Ñ Ğ°Ñ‚Ğ¾Ğ¼Ğ°Ñ€Ğ½Ğ¾ÑÑ‚Ğ¸ Ğ¾Ğ¿ĞµÑ€Ğ°Ñ†Ğ¸Ğ¹ (Ğ½Ğ°Ğ¿Ñ€Ğ¸Ğ¼ĞµÑ€, Ğ¸Ğ´ĞµĞ¼Ğ¿Ğ¾Ñ‚ĞµĞ½Ñ‚Ğ½Ğ¾ÑÑ‚ÑŒ).
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
