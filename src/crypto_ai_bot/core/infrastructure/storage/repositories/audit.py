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
    Репозиторий для записи событий в таблицу `audit`.
    Основной метод: write(event, payload). Алиас: add(event, payload).
    Ожидает действительный SQLite-connection (conn.cursor().execute(...)).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def write(self, event: str, payload: dict[str, Any]) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO audit (event, payload_json, ts_ms) "
            "VALUES (?, json(?), CAST(STRFTIME('%s','now') AS INTEGER)*1000)",
            (event, _json_dumps_safe(payload)),
        )
        self._conn.commit()

    # Для обратной совместимости со старым именем:
    def add(self, event: str, payload: dict[str, Any]) -> None:
        self.write(event, payload)
