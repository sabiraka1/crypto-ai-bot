# src/crypto_ai_bot/core/storage/repositories/decisions.py
from __future__ import annotations

import json
import time
import sqlite3
from typing import Any, Dict, List, Optional


class SqliteDecisionsRepository:
    """
    Таблица decisions:
      id INTEGER PK
      ts_ms INTEGER
      symbol TEXT
      timeframe TEXT
      decision_json TEXT
      explain_json TEXT
      score REAL
      action TEXT
    """
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                explain_json TEXT NULL,
                score REAL NULL,
                action TEXT NULL
            );
            """
        )
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts_ms);")
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_decisions_sym_tf ON decisions(symbol, timeframe);")

    def insert(self, *, symbol: str, timeframe: str, decision: Dict[str, Any], explain: Optional[Dict[str, Any]] = None) -> None:
        ts_ms = int(time.time() * 1000)
        score = None
        action = None
        try:
            score = (decision or {}).get("score")
            action = (decision or {}).get("action")
        except Exception:
            pass
        with self.con:
            self.con.execute(
                "INSERT INTO decisions(ts_ms, symbol, timeframe, decision_json, explain_json, score, action) VALUES (?,?,?,?,?,?,?)",
                (ts_ms, symbol, timeframe, json.dumps(decision or {}), json.dumps(explain or {}), score, action),
            )

    def list_recent(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.con.execute(
            "SELECT ts_ms, symbol, timeframe, decision_json, explain_json, score, action "
            "FROM decisions ORDER BY ts_ms DESC LIMIT ?",
            (int(limit),)
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for ts_ms, symbol, timeframe, djs, ejs, score, action in rows:
            try:
                d = json.loads(djs) if djs else {}
            except Exception:
                d = {}
            try:
                e = json.loads(ejs) if ejs else {}
            except Exception:
                e = {}
            out.append({
                "ts_ms": ts_ms,
                "symbol": symbol,
                "timeframe": timeframe,
                "decision": d,
                "explain": e,
                "score": score,
                "action": action,
            })
        return out
