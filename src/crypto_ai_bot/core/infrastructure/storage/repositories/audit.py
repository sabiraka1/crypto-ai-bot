from __future__ import annotations

from typing import Any, Dict


class AuditRepo:
    """Простой аудиторий. Имеет и write(), и add() для совместимости."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def write(self, event: str, payload: Dict[str, Any]) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO audit (event, payload_json, ts_ms) VALUES (?, json(?), strftime('%s','now')*1000)",
            (event, json_dumps_safe(payload)),
        )
        self._conn.commit()

    # совместимость со старым интерфейсом
    def add(self, event: str, payload: Dict[str, Any]) -> None:
        self.write(event, payload)


def json_dumps_safe(obj: Any) -> str:
    try:
        import json
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"
