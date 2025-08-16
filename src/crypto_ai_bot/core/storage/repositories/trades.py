from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

class TradeRepository:
    """
    SQLite репозиторий сделок.
    Ожидаемая таблица trades (рекомендовано):
      id TEXT PRIMARY KEY,
      symbol TEXT,
      pnl_usd REAL,      -- может называться pnl
      fee_usd REAL NULL,
      closed_at_ms INTEGER
    Реализация толерантна к вариациям схем.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._con = conn

    # -------- базовые операции --------
    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        # Пытаемся использовать pnl_usd, иначе pnl
        try:
            cur = self._con.execute(
                """SELECT id, symbol, COALESCE(pnl_usd, pnl) AS pnl_usd, closed_at_ms
                   FROM trades
                   ORDER BY COALESCE(closed_at_ms, 0) DESC
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
                    "symbol": r[1],
                    "pnl_usd": float(r[2]) if r[2] is not None else None,
                    "closed_at_ms": int(r[3]) if r[3] is not None else None,
                })
            except Exception:
                continue
        return out

    # -------- быстрые агрегаты --------
    def get_seq_losses_fast(self, limit: int = 20) -> int:
        """
        Считает количество последовательных убыточных сделок, начиная с самых последних.
        """
        try:
            cur = self._con.execute(
                """SELECT COALESCE(pnl_usd, pnl) AS pnl_usd
                   FROM trades
                   ORDER BY COALESCE(closed_at_ms, 0) DESC
                   LIMIT ?""",
                (int(limit),),
            )
            rows = cur.fetchall()
        except Exception:
            return 0
        cnt = 0
        for r in rows or []:
            try:
                pnl = float(r[0] or 0.0)
            except Exception:
                pnl = 0.0
            if pnl < 0:
                cnt += 1
            else:
                break
        return cnt

    def get_pnl_summary(self, days: int = 1) -> Dict[str, Optional[float]]:
        """
        Возвращает {'day_pnl_usd': X, 'equity_usd': Y?} за последние N дней.
        Если нет таблицы equity — equity_usd может быть None.
        """
        # день в мс
        ms = int(days) * 24 * 3600 * 1000
        try:
            cur = self._con.execute("SELECT strftime('%s','now') * 1000")
            now_ms = int(cur.fetchone()[0])
        except Exception:
            # best effort — системное время
            import time
            now_ms = int(time.time() * 1000)
        from_ms = now_ms - ms
        # Суммарный PnL за период
        try:
            cur2 = self._con.execute(
                """SELECT SUM(COALESCE(pnl_usd, pnl)) AS s
                   FROM trades
                   WHERE COALESCE(closed_at_ms, 0) >= ?""",
                (from_ms,),
            )
            row = cur2.fetchone()
            day_pnl = float(row[0]) if row and row[0] is not None else 0.0
        except Exception:
            day_pnl = 0.0

        # equity (если ведётся отдельной таблицей)
        equity = None
        try:
            cur3 = self._con.execute(
                """SELECT equity_usd
                   FROM account_equity
                   ORDER BY ts_ms DESC
                   LIMIT 1"""
            )
            r3 = cur3.fetchone()
            if r3 and r3[0] is not None:
                equity = float(r3[0])
        except Exception:
            pass

        return {"day_pnl_usd": day_pnl, "equity_usd": equity}
