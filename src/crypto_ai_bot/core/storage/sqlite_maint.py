# src/crypto_ai_bot/core/storage/sqlite_adapter.py
from __future__ import annotations

import sqlite3
import time
from typing import Callable, Iterable, Optional, Tuple, Any
from .sqlite_adapter import apply_connection_pragmas, connect, execute, executemany  # и др., если нужны
__all__ = ["apply_connection_pragmas", "connect", "execute", "executemany"]


DEFAULT_BUSY_TIMEOUT_MS = 5000
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_MS = 50


def connect(path: str) -> sqlite3.Connection:
    """
    Надёжное подключение к SQLite:
      - autocommit (isolation_level=None)
      - check_same_thread=False (мы сами сериализуем операции на уровне репозиториев)
      - PRAGMA journal_mode=WAL, synchronous=NORMAL, busy_timeout
    """
    con = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=DEFAULT_BUSY_TIMEOUT_MS / 1000.0)
    # базовые pragma
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _retry_write(fn: Callable[[], Any], attempts: int = DEFAULT_RETRY_ATTEMPTS, backoff_ms: int = DEFAULT_RETRY_BACKOFF_MS) -> Any:
    """
    Примитивный retry для write-операций по 'database is locked'.
    """
    last_err: Optional[Exception] = None
    for i in range(max(1, attempts)):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "database is locked" in msg or "busy" in msg:
                last_err = e
                time.sleep(backoff_ms / 1000.0)
                continue
            raise
    if last_err:
        raise last_err


def execute(con: sqlite3.Connection, sql: str, params: Tuple = ()) -> sqlite3.Cursor:
    """
    Обёртка для write (INSERT/UPDATE/DELETE) с retry.
    """
    def _do():
        return con.execute(sql, params)
    return _retry_write(_do)


def executemany(con: sqlite3.Connection, sql: str, seq_of_params: Iterable[Tuple]) -> sqlite3.Cursor:
    def _do():
        return con.executemany(sql, seq_of_params)
    return _retry_write(_do)
