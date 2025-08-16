from __future__ import annotations
import sqlite3, time, json
from typing import Any, Dict, List

from ..interfaces import AuditRepository

CREATE_SQL = '''
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts DESC);
'''

class SqliteAuditRepository(AuditRepository):
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.con.executescript(CREATE_SQL)

    def log(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.con.execute(
            "INSERT INTO audit(ts,event_type,payload) VALUES(?,?,?);",
            (int(time.time()*1000), event_type, json.dumps(payload, ensure_ascii=False)),
        )

    def list_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        cur = self.con.execute("SELECT id,ts,event_type,payload FROM audit ORDER BY ts DESC LIMIT ?;", (int(limit),))
        out = []
        for row in cur.fetchall():
            out.append({
                "id": int(row[0]),
                "ts": int(row[1]),
                "event_type": row[2],
                "payload": json.loads(row[3] or "{}"),
            })
        return out
