# src/crypto_ai_bot/core/storage/sqlite_adapter.py
from __future__ import annotations

import os
import sqlite3
from typing import Dict, Any

from crypto_ai_bot.utils import metrics


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def connect(path: str) -> sqlite3.Connection:
    """
    Подключение SQLite с безопасными прагмами + WAL.
    """
    _ensure_dir(path or "crypto.db")
    con = sqlite3.connect(path or "crypto.db", check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def snapshot_metrics(con: sqlite3.Connection) -> Dict[str, Any]:
    """
    Снимает ключевые метрики состояния БД и выставляет gauge’и:
      - sqlite_page_size_bytes
      - sqlite_page_count
      - sqlite_freelist_pages
      - sqlite_fragmentation_percent
      - sqlite_file_size_bytes
    Возвращает словарь этих значений.
    """
    try:
        page_size = int(con.execute("PRAGMA page_size;").fetchone()[0])
        page_count = int(con.execute("PRAGMA page_count;").fetchone()[0])
        freelist = int(con.execute("PRAGMA freelist_count;").fetchone()[0])
    except Exception:
        # если что-то не получилось — не ломаем экспорт
        page_size = page_count = freelist = 0

    file_size = page_size * page_count
    fragmentation = (freelist / page_count * 100.0) if page_count > 0 else 0.0

    metrics.gauge("sqlite_page_size_bytes", float(page_size))
    metrics.gauge("sqlite_page_count", float(page_count))
    metrics.gauge("sqlite_freelist_pages", float(freelist))
    metrics.gauge("sqlite_fragmentation_percent", float(fragmentation))
    metrics.gauge("sqlite_file_size_bytes", float(file_size))

    return {
        "page_size": page_size,
        "page_count": page_count,
        "freelist_pages": freelist,
        "file_size_bytes": file_size,
        "fragmentation_percent": fragmentation,
    }

# --- Backward-compatible exports expected by core.storage.__init__ ---
from contextlib import contextmanager

@contextmanager
def in_txn(con: "sqlite3.Connection"):
    """
    Transaction context manager for SQLite.
    Commits on success, rolls back on exception.
    """
    try:
        con.execute("BEGIN")
        yield con
        con.commit()
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise


class SqliteUnitOfWork:
    """
    Minimal Unit of Work wrapper over a SQLite connection.
    Usage:
        with SqliteUnitOfWork(con) as uow:
            con.execute(...)
    """
    def __init__(self, con: "sqlite3.Connection"):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            try:
                self.con.commit()
            finally:
                return False
        else:
            try:
                self.con.rollback()
            finally:
                return False


def get_db_stats(con: "sqlite3.Connection") -> dict:
    """Return lightweight DB stats similar to snapshot_metrics, but without gauges."""
    try:
        page_size = int(con.execute("PRAGMA page_size;").fetchone()[0])
        page_count = int(con.execute("PRAGMA page_count;").fetchone()[0])
        freelist = int(con.execute("PRAGMA freelist_count;").fetchone()[0])
    except Exception:
        page_size = page_count = freelist = 0
    file_size = page_size * page_count
    fragmentation = (freelist / page_count * 100.0) if page_count > 0 else 0.0
    return {
        "page_size": page_size,
        "page_count": page_count,
        "freelist_pages": freelist,
        "file_size_bytes": file_size,
        "fragmentation_percent": fragmentation,
    }


def perform_maintenance(con: "sqlite3.Connection") -> dict:
    """Perform a safe maintenance step (PRAGMA optimize) and return post-stats."""
    try:
        con.execute("PRAGMA optimize;")
    except Exception:
        # ignore if not supported
        pass
    return get_db_stats(con)
