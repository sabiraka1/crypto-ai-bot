from __future__ import annotations

import json
from typing import Any


def _json_dumps_safe(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"


class AuditRepo:
    """
    Аудит-репозиторий для записи событий в таблицу `audit`.
    Совместим и с .write(...), и со старым .add(...).
    Ожидает SQLite-подобный connection (conn.cursor().execute(...)).
    """

    def __init__(self, conn) -> None:
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
