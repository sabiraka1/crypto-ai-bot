from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
"""

def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "ts": row["ts"],
        "type": row["type"],
        "payload": json.loads(row["payload"]) if row["payload"] else None,
    }

class SqliteAuditRepository:
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.con.row_factory = sqlite3.Row
        with self.con:
            self.con.executescript(_SCHEMA)

    def append(self, event: Dict[str, Any]) -> int:
        with self.con:
            cur = self.con.execute(
                "INSERT INTO audit(ts, type, payload) VALUES(:ts, :type, :payload)",
                {"ts": event.get("ts"), "type": event.get("type"), "payload": json.dumps(event)},
            )
            return int(cur.lastrowid)

    def list_recent(self, limit: int = 200) -> List[Dict[str, Any]]:
        cur = self.con.execute(
            "SELECT * FROM audit ORDER BY ts DESC LIMIT ?",
            (int(limit),),
        )
        return [_row_to_dict(r) for r in cur.fetchall()]
