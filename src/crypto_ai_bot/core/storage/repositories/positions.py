from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

class PositionRepository:
    """
    SQLite репозиторий позиций.
    Требуемые (желательные) поля таблицы positions:
      id TEXT PRIMARY KEY,
      symbol TEXT,
      side TEXT,              -- 'buy'|'sell'
      amount REAL,
      entry_price REAL,
      status TEXT,            -- 'open'|'closed'
      opened_at_ms INTEGER,
      closed_at_ms INTEGER NULL
    Реализация дружелюбна к различиям схемы: если части полей нет — будет best-effort.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._con = conn

    # -------- базовые операции (минимум API, чтобы не ломать старый код) --------
    def get_open(self) -> List[Dict[str, Any]]:
        try:
            cur = self._con.execute(
                """SELECT id, symbol, side, amount, entry_price
                   FROM positions
                   WHERE status = 'open'"""
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
                    "side": r[2],
                    "amount": float(r[3]) if r[3] is not None else None,
                    "entry_price": float(r[4]) if r[4] is not None else None,
                })
            except Exception:
                continue
        return out

    # -------- быстрый агрегат для экспозиции --------
    def get_open_exposure_fast(self, *, symbol: Optional[str] = None) -> Dict[str, Optional[float]]:
        """
        Возвращает {exposure_usd, exposure_pct?}.
        Для скорости пытается использовать предрасчитанные колонки, если они есть.
        По умолчанию exposure_usd = SUM(ABS(amount * entry_price)) по открытым позициям.
        exposure_pct возвращается только если в таблице присутствует колонка equity_usd (необязательно).
        """
        where = "WHERE status = 'open'"
        params: tuple = ()
        if symbol:
            where += " AND symbol = ?"
            params = (symbol,)
        # Быстрый путь через entry_price*amount
        try:
            cur = self._con.execute(
                f"""SELECT SUM(ABS(COALESCE(amount,0) * COALESCE(entry_price,0))) AS exposure_usd
                    FROM positions
                    {where}""",
                params,
            )
            row = cur.fetchone()
            exposure_usd = float(row[0]) if row and row[0] is not None else None
        except Exception:
            exposure_usd = None

        # Пытаемся достать equity_usd из последней записи (если кто-то пишет туда снимки)
        exposure_pct = None
        if exposure_usd is not None:
            try:
                cur2 = self._con.execute(
                    "SELECT equity_usd FROM account_equity ORDER BY ts_ms DESC LIMIT 1"
                )
                r2 = cur2.fetchone()
                if r2 and r2[0]:
                    eq = float(r2[0])
                    if eq > 0:
                        exposure_pct = exposure_usd / eq * 100.0
            except Exception:
                pass

        return {"exposure_usd": exposure_usd, "exposure_pct": exposure_pct}
