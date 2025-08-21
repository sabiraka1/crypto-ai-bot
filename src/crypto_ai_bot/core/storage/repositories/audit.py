from __future__ import annotations
import sqlite3, json
from typing import List, Dict
from crypto_ai_bot.core.storage.repositories import ensure_schema


class AuditRepositoryImpl:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        ensure_schema(self.conn)

    def log_event(self, event: str, details: dict) -> None:
        self.conn.execute(
            "INSERT INTO audit_log(event, details, ts_ms) VALUES (?, ?, strftime('%s','now')*1000)",
            (event, json.dumps(details, ensure_ascii=False)),
        )
        self.conn.commit()

    def get_recent_events(self, *, limit: int = 100) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT id, event, details, ts_ms FROM audit_log ORDER BY id DESC LIMIT ?", (int(limit),))
        rows = cur.fetchall()
        cur.close()
        out: list[dict] = []
        for rid, event, details, ts_ms in rows:
            try:
                d = json.loads(details) if details else None
            except Exception:
                d = {"raw": details}
            out.append({"id": int(rid), "event": event, "details": d, "ts_ms": int(ts_ms)})
        return out
