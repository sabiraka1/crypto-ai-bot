from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional, Dict, Any

# NOTE: все подключения проходят через этот адаптер. Включаем WAL и таймауты.


def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=5000;")
    return con


@contextmanager
def in_txn(con: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    """
    Контекст менеджер транзакции (BEGIN IMMEDIATE → COMMIT/ROLLBACK).
    """
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE;")
        yield cur
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        cur.close()


class SqliteUnitOfWork:
    """
    Простой UnitOfWork, совместимый с тестами:
      with SqliteUnitOfWork(con) as cur:
          cur.execute(...)
    """
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.cur: Optional[sqlite3.Cursor] = None

    def __enter__(self) -> sqlite3.Cursor:
        self.cur = self.con.cursor()
        self.cur.execute("BEGIN IMMEDIATE;")
        return self.cur

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.con.commit()
            else:
                self.con.rollback()
        finally:
            if self.cur is not None:
                self.cur.close()
                self.cur = None


def get_db_stats(con: sqlite3.Connection) -> Dict[str, Any]:
    try:
        page_count = con.execute("PRAGMA page_count;").fetchone()[0]
        page_size = con.execute("PRAGMA page_size;").fetchone()[0]
        wal_autocheckpoint = con.execute("PRAGMA wal_autocheckpoint;").fetchone()[0]
        return {
            "page_count": int(page_count),
            "page_size": int(page_size),
            "approx_size_bytes": int(page_count) * int(page_size),
            "wal_autocheckpoint": int(wal_autocheckpoint),
        }
    except Exception:
        return {"page_count": None, "page_size": None, "approx_size_bytes": None, "wal_autocheckpoint": None}


def perform_maintenance(con: sqlite3.Connection) -> Dict[str, Any]:
    stats_before = get_db_stats(con)
    try:
        con.execute("PRAGMA optimize;")
        con.execute("PRAGMA analysis_limit=400;")
        con.execute("PRAGMA analyze;")
    except Exception:
        pass
    stats_after = get_db_stats(con)
    return {"before": stats_before, "after": stats_after}
