## `core/storage/repositories/audit.py`
from __future__ import annotations
import sqlite3
import json
from typing import Any, Dict, List, Tuple
from ....utils.time import now_ms
class AuditRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn
    def log(self, action: str, payload: Dict[str, Any]) -> int:
        cur = self._c.execute(
            "INSERT INTO audit_log(action, payload, ts_ms) VALUES (?, ?, ?)",
            (action, json.dumps(payload, ensure_ascii=True, separators=(",", ":")), now_ms()),
        )
        return int(cur.lastrowid)
    def list_recent(self, limit: int = 100) -> List[Tuple[int, str, Dict[str, Any], int]]:
        cur = self._c.execute("SELECT id, action, payload, ts_ms FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        out: List[Tuple[int, str, Dict[str, Any], int]] = []
        for row in cur.fetchall():
            try:
                payload = json.loads(row[2])
            except Exception:
                payload = {"raw": row[2]}
            out.append((int(row[0]), row[1], payload, int(row[3])))
        return out