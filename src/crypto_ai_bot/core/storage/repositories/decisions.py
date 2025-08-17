from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional


def _as_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return format(val, "f")
    return str(val)


@dataclass
class SqliteDecisionsRepository:
    """
    Хранение принятых решений (Decision) для последующей explainability.
    Схема создаётся через миграции (0005_decisions.sql).
    """
    con: sqlite3.Connection

    def insert(self, *, symbol: str, timeframe: str, decision: Dict[str, Any]) -> int:
        """
        Сохраняет решение. Возвращает rowid.
        decision ожидается формата:
            {
              "action": "buy|reduce|close|hold",
              "size": Decimal|str|float,
              "sl": Decimal|str|None,
              "tp": Decimal|str|None,
              "trail": Decimal|str|None,
              "score": float|None,
              "explain": dict|None
            }
        """
        action = (decision.get("action") or "hold")
        size   = _as_str(decision.get("size", "0"))
        sl     = _as_str(decision.get("sl"))
        tp     = _as_str(decision.get("tp"))
        trail  = _as_str(decision.get("trail"))
        score  = decision.get("score")
        explain_json = json.dumps(decision.get("explain") or {}, ensure_ascii=False, separators=(",", ":"))

        decided_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

        with self.con:
            cur = self.con.execute(
                """
                INSERT INTO decisions(symbol, timeframe, decided_ms, action, size, sl, tp, trail, score, explain)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (symbol, timeframe, decided_ms, action, size, sl, tp, trail, score, explain_json),
            )
            return int(cur.lastrowid)

    def get_last(self, *, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        row = self.con.execute(
            """
            SELECT id, symbol, timeframe, decided_ms, action, size, sl, tp, trail, score, explain
            FROM decisions
            WHERE symbol = ? AND timeframe = ?
            ORDER BY decided_ms DESC
            LIMIT 1
            """,
            (symbol, timeframe),
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row[0],
            "symbol": row[1],
            "timeframe": row[2],
            "decided_ms": row[3],
            "action": row[4],
            "size": row[5],
            "sl": row[6],
            "tp": row[7],
            "trail": row[8],
            "score": row[9],
            "explain": json.loads(row[10]) if row[10] else {},
        }
