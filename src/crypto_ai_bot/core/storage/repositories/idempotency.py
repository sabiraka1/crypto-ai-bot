from __future__ import annotations
import json, sqlite3, time
from typing import Any, Dict, Optional

from crypto_ai_bot.core.storage.interfaces import IdempotencyRepository

_SCHEMA_OK = False

def _ensure_schema(con: sqlite3.Connection) -> None:
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    con.execute("""
    CREATE TABLE IF NOT EXISTS idempotency (
        key TEXT PRIMARY KEY,
        status TEXT NOT NULL,              -- 'claimed' | 'committed'
        payload_json TEXT NOT NULL,
        result_json  TEXT,
        created_ts   INTEGER NOT NULL,
        updated_ts   INTEGER NOT NULL
    );
    """)
    con.commit()
    _SCHEMA_OK = True

class SqliteIdempotencyRepository(IdempotencyRepository):
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        _ensure_schema(self.con)

    def claim(self, key: str, payload: Dict[str, Any]) -> bool:
        now = int(time.time())
        try:
            self.con.execute(
                "INSERT INTO idempotency(key,status,payload_json,result_json,created_ts,updated_ts) VALUES(?,?,?,?,?,?)",
                (key, 'claimed', json.dumps(payload, ensure_ascii=False), None, now, now),
            )
            self.con.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def commit(self, key: str, result: Dict[str, Any]) -> None:
        now = int(time.time())
        cur = self.con.execute(
            "UPDATE idempotency SET status='committed', result_json=?, updated_ts=? WHERE key=?",
            (json.dumps(result, ensure_ascii=False), now, key),
        )
        if cur.rowcount == 0:
            self.con.execute(
                "INSERT OR IGNORE INTO idempotency(key,status,payload_json,result_json,created_ts,updated_ts) VALUES(?,?,?,?,?,?)",
                (key, 'committed', json.dumps({}, ensure_ascii=False), json.dumps(result, ensure_ascii=False), now, now),
            )
        self.con.commit()

    def release(self, key: str) -> None:
        return

    def check_and_store(self, key: str, payload: Dict[str, Any]) -> Dict[str, Any] | None:
        row = self.con.execute("SELECT status, result_json FROM idempotency WHERE key=?", (key,)).fetchone()
        if row:
            status, result_json = row
            if status == 'committed' and result_json:
                try:
                    return json.loads(result_json)
                except Exception:
                    return {}
            return None
        _ = self.claim(key, payload)
        return None

    def get_original_order(self, key: str) -> Dict[str, Any] | None:
        row = self.con.execute("SELECT result_json FROM idempotency WHERE key=? AND status='committed'", (key,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0]) if row[0] else None
        except Exception:
            return None

def build_idempotency_key(*, symbol: str, side: str, size: str, decision_id: str | None, ts_sec: int | None = None) -> str:
    ts = int(ts_sec or time.time())
    minute = ts - (ts % 60)
    did8 = (decision_id or "")[:8]
    return f"{symbol}:{side}:{size}:{minute}:{did8}"
