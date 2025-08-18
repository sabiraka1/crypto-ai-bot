import sqlite3
import json
import time
from typing import Any, Dict, List, Optional

class SqliteSnapshotRepository:
    """
    Хранение снимков (например, рыночного контекста/стратегических состояний).
    JSON-пэйлоад хранится в text с валидацией на вставке.
    """
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts INTEGER NOT NULL,
          kind TEXT NOT NULL,           -- произвольная метка: 'market', 'decision', ...
          key TEXT,                     -- агрегирующий ключ (symbol, timeframe и пр.)
          payload TEXT NOT NULL         -- json
        );
        """)
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_kind_ts ON snapshots(kind, ts);")
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_key_ts  ON snapshots(key, ts);")

    def insert(self, snapshot: Dict[str, Any]) -> int:
        """
        Ожидает поля: kind:str, key:str|None, payload:dict
        Возвращает id вставленной записи.
        """
        kind = str(snapshot.get("kind") or "generic")
        key: Optional[str] = snapshot.get("key")
        payload = snapshot.get("payload") or {}
        try:
            payload_txt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except Exception as e:
            raise ValueError(f"snapshot payload must be JSON-serializable: {e}") from e

        with self.con:
            cur = self.con.execute(
                "INSERT INTO snapshots(ts, kind, key, payload) VALUES(?,?,?,?)",
                (int(time.time()), kind, key, payload_txt)
            )
            return int(cur.lastrowid)

    def list_recent(self, *, kind: Optional[str] = None, key: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        q = "SELECT id, ts, kind, key, payload FROM snapshots"
        where = []
        args: List[Any] = []
        if kind:
            where.append("kind=?")
            args.append(kind)
        if key:
            where.append("key=?")
            args.append(key)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(max(1, int(limit)))
        cur = self.con.execute(q, tuple(args))
        rows = []
        for (i, ts, k, ky, ptxt) in cur.fetchall():
            try:
                payload = json.loads(ptxt) if ptxt else {}
            except Exception:
                payload = {"_raw": ptxt, "_error": "invalid_json"}
            rows.append({"id": i, "ts": ts, "kind": k, "key": ky, "payload": payload})
        return rows
