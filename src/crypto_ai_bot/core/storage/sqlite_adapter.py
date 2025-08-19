# src/crypto_ai_bot/core/storage/sqlite_adapter.py
from __future__ import annotations

import sqlite3
import time
from typing import Any, Callable, Iterable, Optional, Tuple

DEFAULT_BUSY_TIMEOUT_MS = 5000       # ожидание при блокировке БД
DEFAULT_RETRY_ATTEMPTS = 3           # кол-во повторов на write-операциях
DEFAULT_RETRY_BACKOFF_MS = 50        # пауза между повторами (мс)


def connect(path: str) -> sqlite3.Connection:
    """
    Надёжное подключение к SQLite:
      - autocommit (isolation_level=None)
      - check_same_thread=False (позволяем использование коннекта в нескольких потоках)
      - PRAGMA journal_mode=WAL, synchronous=NORMAL, busy_timeout
      - foreign_keys=ON
    """
    con = sqlite3.connect(
        path,
        isolation_level=None,  # autocommit
        check_same_thread=False,
        timeout=DEFAULT_BUSY_TIMEOUT_MS / 1000.0,
        detect_types=sqlite3.PARSE_DECLTYPES,
    )

    # Базовые настройки надёжности/производительности
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA temp_store=MEMORY")

    return con


def _retry_write(fn: Callable[[], Any],
                 attempts: int = DEFAULT_RETRY_ATTEMPTS,
                 backoff_ms: int = DEFAULT_RETRY_BACKOFF_MS) -> Any:
    """
    Примитивный retry для write-операций по ошибкам блокировки.
    """
    last_err: Optional[Exception] = None
    for _ in range(max(1, attempts)):
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
    Используйте для всех модифицирующих запросов.
    """
    def _do():
        return con.execute(sql, params)
    return _retry_write(_do)


def executemany(con: sqlite3.Connection, sql: str, seq_of_params: Iterable[Tuple]) -> sqlite3.Cursor:
    """
    Обёртка для пакетных write-запросов с retry.
    """
    def _do():
        return con.executemany(sql, seq_of_params)
    return _retry_write(_do)


def apply_connection_pragmas(conn):
    cur = conn.cursor()
    # Безопасные/полезные дефолты для прод-бота
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("PRAGMA foreign_keys=ON;")
    cur.execute("PRAGMA temp_store=MEMORY;")
    cur.execute("PRAGMA busy_timeout=5000;")  # 5s
    cur.close()
    return conn


def snapshot_metrics(conn) -> dict:
    cur = conn.cursor()
    # базовые индикаторы файла БД
    cur.execute("PRAGMA page_count;")
    page_count = cur.fetchone()[0]
    cur.execute("PRAGMA page_size;")
    page_size = cur.fetchone()[0]
    cur.execute("PRAGMA freelist_count;")
    freelist_count = cur.fetchone()[0]
    # попытка мягкого чекпоинта WAL (не обязателен)
    try:
        cur.execute("PRAGMA wal_checkpoint(PASSIVE);")
        wal = cur.fetchall()
    except Exception:
        wal = []
    cur.close()
    return {
        "page_count": int(page_count),
        "page_size": int(page_size),
        "freelist_count": int(freelist_count),
        "db_size_bytes": int(page_count) * int(page_size),
        "wal": wal,
    }

