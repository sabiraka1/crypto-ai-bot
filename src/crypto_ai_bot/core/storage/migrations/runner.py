# src/crypto_ai_bot/core/storage/migrations/runner.py
from __future__ import annotations

import sqlite3
from pathlib import Path


def _versions_dir() -> Path:
    # .../core/storage/migrations/runner.py -> /migrations/versions
    here = Path(__file__).resolve().parent
    return here / "versions"


def _ensure_version_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version TEXT PRIMARY KEY,
            applied_ts INTEGER NOT NULL
        );
        """
    )


def _is_applied(con: sqlite3.Connection, version: str) -> bool:
    cur = con.execute("SELECT 1 FROM schema_version WHERE version = ?;", (version,))
    return cur.fetchone() is not None


def _mark_applied(con: sqlite3.Connection, version: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO schema_version(version, applied_ts) VALUES(?, strftime('%s','now')*1000);",
        (version,),
    )


def apply_all(con: sqlite3.Connection) -> None:
    _ensure_version_table(con)
    vdir = _versions_dir()
    if not vdir.exists():
        return
    # только *.sql, по алфавиту
    for p in sorted(vdir.glob("*.sql")):
        ver = p.name
        if _is_applied(con, ver):
            continue
        sql = p.read_text(encoding="utf-8")
        with con:  # отдельная транзакция на файл
            con.executescript(sql)
            _mark_applied(con, ver)
