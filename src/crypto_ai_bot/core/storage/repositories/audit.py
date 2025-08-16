# src/crypto_ai_bot/core/storage/repositories/audit.py
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

class AuditRepositorySQLite:
    """
    Аудит: свободная схема JSON details, уникальность по idempotency_key (если задан).
    """

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con

    def log(
        self,
        *,
        at_ms: int,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str | None,
        details: Dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        self.con.execute(
            """
            INSERT INTO audit_log (at, actor, action, entity_type, entity_id, details, idempotency_key)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO NOTHING;
            """,
            (
                int(at_ms),
                actor,
                action,
                entity_type,
                entity_id,
                json.dumps(details or {}, ensure_ascii=False),
                idempotency_key,
            ),
        )

    def list_recent(self, limit: int = 200) -> List[Dict[str, Any]]:
        cur = self.con.execute(
            """
            SELECT id, at, actor, action, entity_type, entity_id, details, idempotency_key
            FROM audit_log
            ORDER BY at DESC
            LIMIT ?;
            """,
            (int(limit),),
        )
        out = []
        for r in cur.fetchall():
            out.append(
                {
                    "id": int(r["id"]),
                    "at": int(r["at"]),
                    "actor": r["actor"],
                    "action": r["action"],
                    "entity_type": r["entity_type"],
                    "entity_id": r["entity_id"],
                    "details": json.loads(r["details"] or "{}"),
                    "idempotency_key": r["idempotency_key"],
                }
            )
        return out
