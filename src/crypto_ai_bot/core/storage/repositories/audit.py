from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict


class AuditRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                action TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )

    def log(self, *, action: str, payload: Dict[str, Any]) -> None:
        self._c.execute(
            "INSERT INTO audit_log(ts_ms, action, payload) VALUES(strftime('%s','now')*1000, ?, ?)",
            (action, json.dumps(payload, ensure_ascii=True)),
        )

    def prune_older_than(self, days: int = 7) -> int:
        cur = self._c.execute(
            "DELETE FROM audit_log WHERE ts_ms < (strftime('%s','now') - ?*86400)*1000",
            (int(days),),
        )
        return cur.rowcount or 0