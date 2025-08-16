# src/crypto_ai_bot/core/storage/migrations/runner.py
from __future__ import annotations

import os
import sqlite3
import time
from glob import glob
from typing import Iterable, List, Tuple

SCHEMA_TABLE = "schema_version"


def _ensure_schema_table(con: sqlite3.Connection) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_TABLE} (
            version TEXT PRIMARY KEY,
            applied_at INTEGER NOT NULL
        );
        """
    )
    con.commit()


def _list_applied(con: sqlite3.Connection) -> List[str]:
    _ensure_schema_table(con)
    cur = con.execute(f"SELECT version FROM {SCHEMA_TABLE} ORDER BY version;")
    return [row[0] for row in cur.fetchall()]


def _iter_versions(base_dir: str) -> Iterable[Tuple[str, str]]:
    """
    Возвращает (version_name, sql_path) по возрастанию.
    Ожидается схема: .../versions/NNNN_description.sql
    """
    pattern = os.path.join(base_dir, "versions", "*.sql")
    paths = sorted(glob(pattern))
    for p in paths:
        name = os.path.basename(p)
        yield name, p


def apply_all(con: sqlite3.Connection, *, base_dir: str | None = None) -> List[str]:
    """
    Применяет все недостающие миграции из каталога versions/.
    Возвращает список применённых версий.
    """
    here = os.path.dirname(__file__)
    base = base_dir or here
    applied = set(_list_applied(con))
    applied_now: List[str] = []

    for version, path in _iter_versions(base):
        if version in applied:
            continue
        sql = _read_sql(path)
        _apply_one(con, version, sql)
        applied_now.append(version)

    return applied_now


def _read_sql(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _apply_one(con: sqlite3.Connection, version: str, sql: str) -> None:
    t0 = time.perf_counter()
    with con:  # атомарно
        con.executescript(sql)
        con.execute(
            f"INSERT INTO {SCHEMA_TABLE}(version, applied_at) VALUES(?, ?);",
            (version, int(time.time())),
        )
    _ = time.perf_counter() - t0
