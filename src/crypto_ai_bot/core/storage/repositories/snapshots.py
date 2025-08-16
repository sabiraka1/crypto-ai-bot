from __future__ import annotations
from typing import Any, Dict, List, Optional
import json
from datetime import datetime, timezone

from .base import _WriteCountingRepo

class SnapshotRepository(_WriteCountingRepo):
    """
    Ожидаем схему:
      snapshots(id INTEGER PK, ts INTEGER, symbol TEXT, payload TEXT)
      индексы по (symbol, ts)
    """

    def insert(self, symbol: str, payload: Dict[str, Any], ts: Optional[int] = None) -> None:
        ts = int(ts or datetime.now(tz=timezone.utc).timestamp())
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        cur = self._con.cursor()
        try:
            cur.execute("INSERT INTO snapshots(ts, symbol, payload) VALUES (?, ?, ?)", (ts, symbol, data))
            self._inc_writes("snapshots", 1)
        finally:
            cur.close()

    def recent(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        cur = self._con.cursor()
        try:
            cur.execute("SELECT id, ts, symbol, payload FROM snapshots WHERE symbol=? ORDER BY ts DESC LIMIT ?", (symbol, int(limit)))
            rows = cur.fetchall()
            out = []
            for r in rows:
                try:
                    payload = json.loads(r[3])
                except Exception:
                    payload = None
                out.append({"id": r[0], "ts": r[1], "symbol": r[2], "payload": payload})
            return out
        finally:
            cur.close()
