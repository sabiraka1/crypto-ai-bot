## `core/storage/sqlite_adapter.py`
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        db_path, check_same_thread=False, isolation_level=None
    )  # autocommit; BEGIN ДћВІГ‘в‚¬Г‘Ж’Г‘вЂЎДћВЅГ‘Ж’Г‘ВЋ
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    """BEGIN IMMEDIATE (write txn) + COMMIT/ROLLBACK. ДћвЂ™ДћВѕДћВ·ДћВІГ‘в‚¬ДћВ°Г‘вЂ°ДћВ°ДћВµГ‘вЂљ ДћВєГ‘Ж’Г‘в‚¬Г‘ВЃДћВѕГ‘в‚¬.
    ДћЛњГ‘ВЃДћВїДћВѕДћВ»Г‘Е’ДћВ·Г‘Ж’ДћВµДћВј Г‘ВЏДћВІДћВЅГ‘вЂ№ДћВµ Г‘вЂљГ‘в‚¬ДћВ°ДћВЅДћВ·ДћВ°ДћВєГ‘вЂ ДћВёДћВё ДћВґДћВ»Г‘ВЏ ДћВ°Г‘вЂљДћВѕДћВјДћВ°Г‘в‚¬ДћВЅДћВѕГ‘ВЃГ‘вЂљДћВё ДћВѕДћВїДћВµГ‘в‚¬ДћВ°Г‘вЂ ДћВёДћВ№ (ДћВЅДћВ°ДћВїГ‘в‚¬ДћВёДћВјДћВµГ‘в‚¬, ДћВёДћВґДћВµДћВјДћВїДћВѕГ‘вЂљДћВµДћВЅГ‘вЂљДћВЅДћВѕГ‘ВЃГ‘вЂљГ‘Е’).
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
