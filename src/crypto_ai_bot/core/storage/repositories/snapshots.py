# src/crypto_ai_bot/core/storage/repositories/snapshots.py
from __future__ import annotations
import json
from typing import Any, Dict, Optional
import sqlite3

from crypto_ai_bot.core.storage.interfaces import SnapshotRepository


class SqliteSnapshotRepository(SnapshotRepository):  # type: ignore[misc]
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    def upsert(self, snap: Dict[str, Any]) -> None:
        self._con.execute(
            """
            INSERT INTO snapshots(symbol, payload_json, ts)
            VALUES(:symbol, :payload_json, :ts);
            """,
            {
                "symbol": snap["symbol"],
                "payload_json": json.dumps(snap["payload"], ensure_ascii=False, separators=(",", ":")),
                "ts": int(snap["ts"]),
            },
        )

    def get_last(self, symbol: str) -> Optional[Dict[str, Any]]:
        cur = self._con.execute(
            "SELECT * FROM snapshots WHERE symbol = ? ORDER BY ts DESC LIMIT 1;",
            (symbol,),
        )
        r = cur.fetchone()
        if not r:
            return None
        return {"symbol": r["symbol"], "payload": json.loads(r["payload_json"] or "{}"), "ts": int(r["ts"])}
