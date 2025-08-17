from __future__ import annotations

from pathlib import Path
from typing import Iterable
import sqlite3


def _versions_dir() -> Path:
    return Path(__file__).parent / "versions"


def latest_version() -> int:
    """Берём макс. префикс из файлов вида 0001_*.sql"""
    mx = 0
    for p in _versions_dir().glob("*.sql"):
        try:
            v = int(p.stem.split("_", 1)[0])
            mx = max(mx, v)
        except Exception:
            continue
    return mx


def get_current_version(con: sqlite3.Connection) -> int:
    """
    Пытаемся прочитать user_version, иначе — таблицу schema_version.
    """
    try:
        row = con.execute("PRAGMA user_version").fetchone()
        if row is not None:
            v = int(row[0])
            if v:
                return v
    except Exception:
        pass

    try:
        con.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL)")
        row = con.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def apply_all(con: sqlite3.Connection) -> None:
    cur = get_current_version(con)
    target = latest_version()
    if cur >= target:
        return

    versions = sorted(_versions_dir().glob("*.sql"))
    for p in versions:
        v = int(p.stem.split("_", 1)[0])
        if v <= cur:
            continue
        sql = p.read_text(encoding="utf-8")
        with con:
            con.executescript(sql)
            # фиксируем и в user_version, и (на всякий) в schema_version
            con.execute(f"PRAGMA user_version = {v}")
            con.execute("INSERT INTO schema_version(version) VALUES (?)", (v,))


def is_up_to_date(con: sqlite3.Connection) -> bool:
    return get_current_version(con) >= latest_version()
