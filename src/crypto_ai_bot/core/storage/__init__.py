# src/crypto_ai_bot/core/storage/__init__.py
from __future__ import annotations
from typing import Any, Dict
import sqlite3
import os
from contextlib import contextmanager

# --- connect (обязательный); даём fallback на случай отсутствия sqlite_adapter ---
try:
    from .sqlite_adapter import connect  # type: ignore
except Exception:
    def connect(db_path: str | None = None, **kwargs) -> sqlite3.Connection:
        path = db_path or os.getenv("DB_PATH", ":memory:")
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

# --- опциональные утилиты БД ---
try:
    from .sqlite_adapter import get_db_stats  # type: ignore
except Exception:
    pass

try:
    from .sqlite_adapter import perform_maintenance  # type: ignore
except Exception:
    pass

# --- in_txn: ищем под разными именами, иначе даём безопасный fallback ---
try:
    from .sqlite_adapter import in_txn  # type: ignore
except Exception:
    try:
        from .sqlite_adapter import in_transaction as in_txn  # type: ignore
    except Exception:
        try:
            from .sqlite_adapter import transaction as in_txn  # type: ignore
        except Exception:
            @contextmanager
            def in_txn(conn: sqlite3.Connection):
                cur = conn.cursor()
                try:
                    cur.execute("BEGIN")
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    cur.close()

# --- SqliteUnitOfWork: подхватываем разные варианты названий, либо даём fallback ---
_UOW = None
try:
    from .sqlite_adapter import SqliteUnitOfWork as _UOW  # type: ignore
except Exception:
    try:
        from .sqlite_adapter import SQLiteUnitOfWork as _UOW  # type: ignore
    except Exception:
        try:
            from .sqlite_adapter import UnitOfWork as _UOW  # type: ignore
        except Exception:
            try:
                from .sqlite_adapter import SqliteUoW as _UOW  # type: ignore
            except Exception:
                _UOW = None

if _UOW is None:
    class SqliteUnitOfWork:
        """Минимальная совместимая UoW-обёртка для sqlite3.Connection."""
        def __init__(self, conn: sqlite3.Connection):
            self.conn = conn
            self._cur = None

        def __enter__(self):
            self._cur = self.conn.cursor()
            self._cur.execute("BEGIN")
            return self

        def __exit__(self, exc_type, exc, tb):
            try:
                if exc_type is None:
                    self.conn.commit()
                else:
                    self.conn.rollback()
            finally:
                if self._cur is not None:
                    self._cur.close()
                    self._cur = None

        @property
        def connection(self) -> sqlite3.Connection:
            return self.conn
else:
    SqliteUnitOfWork = _UOW  # type: ignore

__all__ = [name for name in (
    "connect",
    "get_db_stats",
    "perform_maintenance",
    "in_txn",
    "SqliteUnitOfWork",
) if name in globals()]
