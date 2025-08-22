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

    # ✅ новый метод ретеншна: по количеству дней
    def prune_older_than(self, *, days: int) -> int:
        """Удалить записи старше указанного количества дней. Возвращает кол-во удалённых записей."""
        if days <= 0:
            return 0
        cutoff = now_ms() - int(days) * 86400000  # 24*60*60*1000
        cur = self._c.execute("DELETE FROM audit_log WHERE ts_ms < ?", (cutoff,))
        return cur.rowcount or 0

    def prune_older_than_days(self, days: int) -> int:
        """
        Удаляет записи старше now - days.
        Возвращает число удалённых строк.
        """
        cutoff_ms = now_ms() - int(days) * 24 * 60 * 60 * 1000
        cur = self._c.cursor()
        cur.execute("DELETE FROM audit_log WHERE ts_ms < ?", (cutoff_ms,))
        n = cur.rowcount or 0
        self._c.commit()
        return n