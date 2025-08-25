from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import List

from ....utils.logging import get_logger

_log = get_logger("migrations")


def _list_migrations(dir_path: Path) -> List[Path]:
    return sorted([p for p in dir_path.glob("V*.sql") if p.is_file()])


def run_migrations(conn: sqlite3.Connection, *, now_ms: int) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at_ms INTEGER NOT NULL
        )
        """
    )
    base = Path(__file__).parent
    for f in _list_migrations(base):
        version = f.stem
        c = cur.execute("SELECT 1 FROM schema_migrations WHERE version=?", (version,)).fetchone()
        if c:
            continue
        sql = f.read_text(encoding="utf-8")
        _log.info("apply_migration", extra={"version": version})
        cur.executescript(sql)
        cur.execute("INSERT INTO schema_migrations(version, applied_at_ms) VALUES(?, ?)", (version, now_ms))
    conn.commit()