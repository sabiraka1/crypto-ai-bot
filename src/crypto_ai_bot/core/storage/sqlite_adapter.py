# src/crypto_ai_bot/core/storage/sqlite_adapter.py
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Optional, Sequence, Tuple, Dict

from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA temp_store=MEMORY;",
    "PRAGMA mmap_size=268435456;",  # 256MB
    "PRAGMA cache_size=-20000;",    # ~20MB
    "PRAGMA foreign_keys=ON;",
)

def apply_connection_pragmas(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for stmt in _DEFAULT_PRAGMAS:
        cur.execute(stmt)
    cur.close()


def connect(db_path: str, *, apply_pragmas: bool = True) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = _dict_factory
    if apply_pragmas:
        apply_connection_pragmas(conn)
    return conn


def _dict_factory(cursor: sqlite3.Cursor, row: Tuple[Any, ...]) -> Dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        yield cur
        cur.execute("COMMIT")
    except Exception:
        cur.execute("ROLLBACK")
        raise
    finally:
        cur.close()


def execute(conn: sqlite3.Connection, sql: str, params: Optional[Sequence[Any]] = None) -> int:
    """
    Выполнить одиночный запрос (INSERT/UPDATE/DELETE). Возвращает rowcount.
    ВНИМАНИЕ: не формируйте f-строки — используйте params.
    """
    cur = conn.cursor()
    try:
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        return cur.rowcount
    finally:
        cur.close()


def executemany(conn: sqlite3.Connection, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> int:
    cur = conn.cursor()
    try:
        cur.executemany(sql, list(seq_of_params))
        return cur.rowcount
    finally:
        cur.close()


def query_one(conn: sqlite3.Connection, sql: str, params: Optional[Sequence[Any]] = None) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    try:
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()


def query_all(conn: sqlite3.Connection, sql: str, params: Optional[Sequence[Any]] = None) -> list[Dict[str, Any]]:
    cur = conn.cursor()
    try:
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
