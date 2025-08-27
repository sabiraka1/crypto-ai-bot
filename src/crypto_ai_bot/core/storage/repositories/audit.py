from __future__ import annotations

import sqlite3
from typing import Any, Dict


class AuditRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                payload TEXT,
                ts_ms INTEGER NOT NULL
            )
            """
        )
        self._c.commit()

    def add(self, action: str, payload: Dict[str, Any], ts_ms: int) -> None:
        self._c.execute(
            "INSERT INTO audit(action, payload, ts_ms) VALUES(?,?,?)",
            (action, str(payload), ts_ms),
        )
        self._c.commit()

    def prune_older_than(self, days: int) -> None:
        # лёгкая ротация по дате (добавь при желании pragma/wal/vacuum в maintenance_cli)
        self._c.execute("DELETE FROM audit WHERE ts_ms < strftime('%s','now')*1000 - ?*24*3600*1000", (days,))
        self._c.commit()
