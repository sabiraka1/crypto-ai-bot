from __future__ import annotations
from typing import Any, Dict, List, Optional
import json
from datetime import datetime, timezone

from .base import _WriteCountingRepo

class AuditRepository(_WriteCountingRepo):
    """
    Ожидаем схему:
      audit(id INTEGER PK, ts INTEGER, event_type TEXT, payload TEXT)
      индексы по (event_type, ts)
    """

    def insert(self, event_type: str, payload: Dict[str, Any], ts: Optional[int] = None) -> None:
        ts = int(ts or datetime.now(tz=timezone.utc).timestamp())
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        cur = self._con.cursor()
        try:
            cur.execute("INSERT INTO audit(ts, event_type, payload) VALUES (?, ?, ?)", (ts, event_type, data))
            self._inc_writes("audit", 1)
        finally:
            cur.close()

    def recent(self, event_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        cur = self._con.cursor()
        try:
            if event_type:
                cur.execute("SELECT id, ts, event_type, payload FROM audit WHERE event_type=? ORDER BY ts DESC LIMIT ?", (event_type, int(limit)))
            else:
                cur.execute("SELECT id, ts, event_type, payload FROM audit ORDER BY ts DESC LIMIT ?", (int(limit),))
            rows = cur.fetchall()
            out = []
            for r in rows:
                try:
                    payload = json.loads(r[3])
                except Exception:
                    payload = None
                out.append({"id": r[0], "ts": r[1], "event_type": r[2], "payload": payload})
            return out
        finally:
            cur.close()
