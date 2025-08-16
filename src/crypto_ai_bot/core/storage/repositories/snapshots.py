# src/crypto_ai_bot/core/storage/repositories/snapshots.py
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

class SnapshotRepositorySQLite:
    """
    Снимки состояния/фич для аудита или последующей аналитики.
    """

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con

    def insert(self, taken_at_ms: int, payload: Dict[str, Any]) -> int:
        cur = self.con.execute(
            "INSERT INTO snapshots (taken_at, payload) VALUES (?, ?);",
            (int(taken_at_ms), json.dumps(payload, ensure_ascii=False)),
        )
        return int(cur.lastrowid)

    def last(self) -> Optional[Dict[str, Any]]:
        cur = self.con.execute(
            "SELECT id, taken_at, payload FROM snapshots ORDER BY taken_at DESC LIMIT 1;"
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row["id"], "taken_at": int(row["taken_at"]), "payload": json.loads(row["payload"] or "{}")}

    def list_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        cur = self.con.execute(
            "SELECT id, taken_at, payload FROM snapshots ORDER BY taken_at DESC LIMIT ?;",
            (int(limit),),
        )
        out = []
        for r in cur.fetchall():
            out.append({"id": r["id"], "taken_at": int(r["taken_at"]), "payload": json.loads(r["payload"] or "{}")})
        return out
