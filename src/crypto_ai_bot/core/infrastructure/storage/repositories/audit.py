from __future__ import annotations

import json
import sqlite3
from typing import Any


def _json_dumps_safe(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"


class AuditRepo:
    """
    ĞÑƒĞ´Ğ¸Ñ‚-Ñ€ĞµĞ¿Ğ¾Ğ·Ğ¸Ñ‚Ğ¾Ñ€Ğ¸Ğ¹ Ğ´Ğ»Ñ Ğ·Ğ°Ğ¿Ğ¸ÑĞ¸ ÑĞ¾Ğ±Ñ‹Ñ‚Ğ¸Ğ¹ Ğ² Ñ‚Ğ°Ğ±Ğ»Ğ¸Ñ†Ñƒ `audit`.
    Ğ¡Ğ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼ Ğ¸ Ñ .write(...), Ğ¸ ÑĞ¾ ÑÑ‚Ğ°Ñ€Ñ‹Ğ¼ .add(...).
    ĞĞ¶Ğ¸Ğ´Ğ°ĞµÑ‚ SQLite-Ğ¿Ğ¾Ğ´Ğ¾Ğ±Ğ½Ñ‹Ğ¹ connection (conn.cursor().execute(...)).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:  # Ğ˜ÑĞ¿Ñ€Ğ°Ğ²Ğ»ĞµĞ½Ğ¾: Ğ´Ğ¾Ğ±Ğ°Ğ²Ğ»ĞµĞ½ Ñ‚Ğ¸Ğ¿
        self._conn = conn

    def write(self, event: str, payload: dict[str, Any]) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO audit (event, payload_json, ts_ms) "
            "VALUES (?, json(?), CAST(STRFTIME('%s','now') AS INTEGER)*1000)",
            (event, _json_dumps_safe(payload)),
        )
        self._conn.commit()

    # Ğ”Ğ»Ñ Ğ¾Ğ±Ñ€Ğ°Ñ‚Ğ½Ğ¾Ğ¹ ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ğ¾ÑÑ‚Ğ¸ ÑĞ¾ ÑÑ‚Ğ°Ñ€Ñ‹Ğ¼ Ğ¸Ğ¼ĞµĞ½ĞµĞ¼:
    def add(self, event: str, payload: dict[str, Any]) -> None:
        self.write(event, payload)
