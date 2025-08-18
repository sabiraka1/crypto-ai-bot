import sqlite3
import json
import time
from typing import Any, Dict, List, Optional


class SqliteAuditRepository:
    """
    Простой аудит-лог: (ts, kind, payload JSON-строкой).
    Используется для технического аудита/расследований.
    """

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts INTEGER NOT NULL,
              kind TEXT NOT NULL,
              payload TEXT
            );
            """
        )
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_audit_kind_ts ON audit_log(kind, ts);")

    def log(self, kind: str, payload: Optional[Any] = None) -> int:
        """
        kind: метка события ('order_placed', 'order_filled', 'sl_trigger', ...)
        payload: dict/str/None — будет сериализован в JSON (или строку)
        """
        if isinstance(payload, (dict, list)):
            payload_txt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        elif payload is None:
            payload_txt = None
        else:
            payload_txt = str(payload)

        with self.con:
            cur = self.con.execute(
                "INSERT INTO audit_log(ts, kind, payload) VALUES(?,?,?)",
                (int(time.time()), kind, payload_txt),
            )
            return int(cur.lastrowid)

    def list_recent(self, kind: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        q = "SELECT id, ts, kind, payload FROM audit_log"
        args: List[Any] = []
        if kind:
            q += " WHERE kind=?"
            args.append(kind)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(max(1, int(limit)))
        cur = self.con.execute(q, tuple(args))
        rows: List[Dict[str, Any]] = []
        for (i, ts, k, ptxt) in cur.fetchall():
            try:
                payload = json.loads(ptxt) if ptxt else None
            except Exception:
                payload = {"_raw": ptxt, "_error": "invalid_json"}
            rows.append({"id": i, "ts": ts, "kind": k, "payload": payload})
        return rows
