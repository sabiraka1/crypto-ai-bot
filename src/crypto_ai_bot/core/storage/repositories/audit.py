from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import json

class AuditRepository:
    """
    Простой репозиторий аудита.
    Таблица: audit_log(id, ts_ms, event_type, trace_id, payload_json)
    - payload_json: произвольный JSON (строка в БД)
    Методы устойчивы к сбоям сериализации/десериализации и не кидают исключения наружу по мелочам.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._con = conn

    # --------------- helpers ---------------
    @staticmethod
    def _now_ms() -> int:
        return int(datetime.now(tz=timezone.utc).timestamp() * 1000)

    @staticmethod
    def _to_json(payload: Any) -> str:
        # Если уже строка — сохраняем как JSON-строку {"message": "..."}
        if isinstance(payload, str):
            return json.dumps({"message": payload}, ensure_ascii=False)
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            # Фоллбэк: best-effort
            return json.dumps({"unserializable": str(payload)}, ensure_ascii=False)

    @staticmethod
    def _from_json(text: str) -> Any:
        try:
            return json.loads(text)
        except Exception:
            return {"raw": text}

    # --------------- API ---------------
    def insert(self, event_type: str, payload: Any, *, trace_id: Optional[str] = None) -> None:
        ts = self._now_ms()
        data = self._to_json(payload)
        try:
            self._con.execute(
                """INSERT INTO audit_log (ts_ms, event_type, trace_id, payload_json)
                   VALUES (?, ?, ?, ?)""",
                (ts, str(event_type), trace_id, data),
            )
            self._con.commit()
        except Exception:
            # Не роняем приложение из-за аудита
            try:
                self._con.rollback()
            except Exception:
                pass

    # Синонимы на случай иного ожидания интерфейса
    def log(self, event_type: str, payload: Any, *, trace_id: Optional[str] = None) -> None:
        self.insert(event_type, payload, trace_id=trace_id)

    def add(self, event_type: str, payload: Any, *, trace_id: Optional[str] = None) -> None:
        self.insert(event_type, payload, trace_id=trace_id)

    def list_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        try:
            cur = self._con.execute(
                """SELECT id, ts_ms, event_type, trace_id, payload_json
                   FROM audit_log
                   ORDER BY ts_ms DESC
                   LIMIT ?""",
                (int(limit),),
            )
            rows = cur.fetchall()
        except Exception:
            return []
        out: List[Dict[str, Any]] = []
        for r in rows or []:
            try:
                out.append({
                    "id": r[0],
                    "ts_ms": r[1],
                    "event_type": r[2],
                    "trace_id": r[3],
                    "payload": self._from_json(r[4] or "{}"),
                })
            except Exception:
                continue
        return out

    def list_by_type(self, event_type: str, limit: int = 100) -> List[Dict[str, Any]]:
        try:
            cur = self._con.execute(
                """SELECT id, ts_ms, event_type, trace_id, payload_json
                   FROM audit_log
                   WHERE event_type = ?
                   ORDER BY ts_ms DESC
                   LIMIT ?""",
                (str(event_type), int(limit)),
            )
            rows = cur.fetchall()
        except Exception:
            return []
        out: List[Dict[str, Any]] = []
        for r in rows or []:
            try:
                out.append({
                    "id": r[0],
                    "ts_ms": r[1],
                    "event_type": r[2],
                    "trace_id": r[3],
                    "payload": self._from_json(r[4] or "{}"),
                })
            except Exception:
                continue
        return out

    def purge_older_than_days(self, days: int) -> int:
        # Возвращает количество удалённых записей
        try:
            ms = int(days) * 24 * 3600 * 1000
            threshold = self._now_ms() - ms
            cur = self._con.execute("DELETE FROM audit_log WHERE ts_ms < ?", (threshold,))
            self._con.commit()
            return cur.rowcount or 0
        except Exception:
            try:
                self._con.rollback()
            except Exception:
                pass
            return 0
