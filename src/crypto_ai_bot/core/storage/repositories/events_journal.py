# src/crypto_ai_bot/core/storage/repositories/events_journal.py
from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS events_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,        -- enqueued | delivered | error
    request_id TEXT,
    correlation_id TEXT,
    payload TEXT                  -- json (ограничим размером в коде)
);
CREATE INDEX IF NOT EXISTS idx_events_journal_ts ON events_journal(ts_ms);
CREATE INDEX IF NOT EXISTS idx_events_journal_type ON events_journal(type);
CREATE INDEX IF NOT EXISTS idx_events_journal_status ON events_journal(status);
"""

class EventJournalRepository:
    """
    Простой журнал событий в SQLite с ограничением максимального числа записей (ring-buffer).
    Логируем минимум: ts_ms, type, status, request_id/correlation_id, payload (усечённый).
    """

    def __init__(self, con, *, max_rows: int = 10_000, max_payload_bytes: int = 2048) -> None:
        self._con = con
        self._max_rows = int(max_rows)
        self._max_payload = int(max_payload_bytes)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._con.executescript(_CREATE_SQL)
        self._con.commit()

    def _prune_if_needed(self) -> None:
        if self._max_rows <= 0:
            return
        cur = self._con.execute("SELECT MAX(id), COUNT(1) FROM events_journal")
        row = cur.fetchone() or (None, 0)
        max_id, cnt = (int(row[0]) if row[0] is not None else 0, int(row[1] or 0))
        if cnt > self._max_rows:
            cutoff = max_id - self._max_rows
            self._con.execute("DELETE FROM events_journal WHERE id <= ?", (cutoff,))
            self._con.commit()

    def _truncate_payload(self, payload: Any) -> str:
        try:
            s = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            s = str(payload)
        if len(s.encode("utf-8")) > self._max_payload:
            # мягко обрежем
            enc = s.encode("utf-8")[: self._max_payload]
            try:
                s = enc.decode("utf-8", errors="ignore")
            except Exception:
                s = s[: self._max_payload // 2]
        return s

    def insert(self, *, ts_ms: Optional[int], type_: str, status: str,
               request_id: Optional[str], correlation_id: Optional[str], payload: Any) -> None:
        if not ts_ms:
            ts_ms = int(time.time() * 1000)
        self._con.execute(
            "INSERT INTO events_journal (ts_ms, type, status, request_id, correlation_id, payload) VALUES (?,?,?,?,?,?)",
            (int(ts_ms), str(type_), str(status), request_id, correlation_id, self._truncate_payload(payload)),
        )
        self._con.commit()
        self._prune_if_needed()

    # удобные хелперы
    def log_enqueued(self, evt: Dict[str, Any]) -> None:
        self.insert(
            ts_ms=int(evt.get("ts_ms") or int(time.time() * 1000)),
            type_=str(evt.get("type") or "Unknown"),
            status="enqueued",
            request_id=evt.get("request_id"),
            correlation_id=evt.get("correlation_id"),
            payload=evt,
        )

    def log_delivered(self, evt: Dict[str, Any]) -> None:
        self.insert(
            ts_ms=int(evt.get("ts_ms") or int(time.time() * 1000)),
            type_=str(evt.get("type") or "Unknown"),
            status="delivered",
            request_id=evt.get("request_id"),
            correlation_id=evt.get("correlation_id"),
            payload=evt,
        )

    def log_error(self, evt: Dict[str, Any], err: Exception) -> None:
        payload = dict(evt)
        payload["__error__"] = f"{type(err).__name__}: {err}"
        self.insert(
            ts_ms=int(evt.get("ts_ms") or int(time.time() * 1000)),
            type_=str(evt.get("type") or "Unknown"),
            status="error",
            request_id=evt.get("request_id"),
            correlation_id=evt.get("correlation_id"),
            payload=payload,
        )

    # агрегаты для /bus/stats
    def stats(self, *, since_ms: Optional[int] = None) -> Dict[str, Any]:
        where = "WHERE 1=1"
        args: List[Any] = []
        if since_ms is not None:
            where += " AND ts_ms >= ?"
            args.append(int(since_ms))

        # totals
        cur = self._con.execute(f"SELECT status, COUNT(1) FROM events_journal {where} GROUP BY status", args)
        totals = {row[0]: int(row[1]) for row in cur.fetchall()}

        # by type & status
        cur = self._con.execute(
            f"SELECT type, status, COUNT(1) FROM events_journal {where} GROUP BY type, status", args
        )
        by_type: Dict[str, Dict[str, int]] = {}
        for t, st, c in cur.fetchall():
            by_type.setdefault(t, {})[st] = int(c)

        # last N items (для UI/диагностики)
        cur = self._con.execute(
            f"SELECT ts_ms, type, status, request_id, correlation_id, payload FROM events_journal {where} ORDER BY id DESC LIMIT 50",
            args,
        )
        last = []
        for ts_ms, type_, status, rid, cid, payload in cur.fetchall():
            try:
                p = json.loads(payload)
            except Exception:
                p = payload
            last.append(
                {
                    "ts_ms": int(ts_ms),
                    "type": type_,
                    "status": status,
                    "request_id": rid,
                    "correlation_id": cid,
                    "payload": p,
                }
            )

        return {"totals": totals, "by_type": by_type, "last": last}
