from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
import os
import sqlite3

DEFAULT_BUSY_TIMEOUT_MS = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "8000"))
DEFAULT_PAGE_SIZE = int(os.getenv("SQLITE_PAGE_SIZE", "4096"))

__all__ = [
    "connect",
    "transaction",
    "read_only",
    "exec_script",
]


def connect(db_path: str) -> sqlite3.Connection:
    """
    Создаёт подключение SQLite с разумными PRAGMA:
      - WAL журналирование для конкуренции,
      - NORMAL synchronous,
      - busy_timeout (настраиваемый через ENV),
      - foreign_keys ON.
    Автокоммит выключен (isolation_level=None) — транзакции управляем вручную.
    """
    conn = sqlite3.connect(
        db_path,
        check_same_thread=False,
        isolation_level=None,  # autocommit; BEGIN делаем вручную
        timeout=DEFAULT_BUSY_TIMEOUT_MS / 1000.0,
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    # PRAGMA'и не приводят к ошибкам, если окружение не поддерживает конкретные значения
    with suppress(Exception):
        conn.execute("PRAGMA journal_mode=WAL;")
    with suppress(Exception):
        conn.execute("PRAGMA synchronous=NORMAL;")
    with suppress(Exception):
        conn.execute("PRAGMA temp_store=MEMORY;")
    with suppress(Exception):
        conn.execute("PRAGMA foreign_keys=ON;")
    with suppress(Exception):
        conn.execute(f"PRAGMA page_size={DEFAULT_PAGE_SIZE};")
    with suppress(Exception):
        conn.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS};")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    """
    BEGIN IMMEDIATE (write txn) + COMMIT/ROLLBACK. Возвращает курсор.
    Использовать для атомарных операций (например, идемпотентность, пакетные апдейты).
    """
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE;")
    try:
        yield cur
        conn.commit()
    except Exception:
        with suppress(Exception):
            conn.rollback()
        raise
    finally:
        with suppress(Exception):
            cur.close()


@contextmanager
def read_only(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    """
    BEGIN DEFERRED (read txn) + COMMIT/ROLLBACK. Возвращает курсор.
    Удобно для консистентного чтения нескольких таблиц.
    """
    cur = conn.cursor()
    cur.execute("BEGIN;")
    try:
        yield cur
        conn.commit()
    except Exception:
        with suppress(Exception):
            conn.rollback()
        raise
    finally:
        with suppress(Exception):
            cur.close()


def exec_script(conn: sqlite3.Connection, sql: str) -> None:
    """Безопасно выполнить многооператорный SQL-скрипт в транзакции."""
    if not sql or not sql.strip():
        return
    with conn:
        conn.executescript(sql)
