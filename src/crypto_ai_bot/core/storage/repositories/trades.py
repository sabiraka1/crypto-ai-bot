# src/crypto_ai_bot/core/storage/repositories/trades.py
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size TEXT NOT NULL,
    price TEXT NOT NULL,
    fee TEXT,
    ts TEXT NOT NULL,
    payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts);
"""

def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "position_id": row["position_id"],
        "symbol": row["symbol"],
        "side": row["side"],
        "size": row["size"],
        "price": row["price"],
        "fee": row["fee"],
        "ts": row["ts"],
        "payload": json.loads(row["payload"]) if row["payload"] else None,
    }

def _to_dec(x: Any) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0")

def _parse_ts(ts: str) -> datetime:
    # Поддерживаем ISO-8601; на всякий случай пробуем разные парсеры
    try:
        # ISO with 'Z'
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return datetime.fromisoformat(ts)
    except Exception:
        # Фолбэк — трактуем как UTC-строку «YYYY-MM-DD HH:MM:SS»
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            # если всё плохо — ставим «старую» дату, чтобы не мешать расчётам
            return datetime(1970, 1, 1, tzinfo=timezone.utc)

class SqliteTradeRepository:
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.con.row_factory = sqlite3.Row
        with self.con:
            self.con.executescript(_SCHEMA)

    def insert(self, trade: Dict[str, Any]) -> int:
        with self.con:
            cur = self.con.execute(
                """
                INSERT INTO trades(position_id, symbol, side, size, price, fee, ts, payload)
                VALUES(:position_id, :symbol, :side, :size, :price, :fee, :ts, :payload)
                """,
                {**trade, "payload": json.dumps(trade.get("payload")) if trade.get("payload") is not None else None},
            )
            return int(cur.lastrowid)

    def list_by_symbol(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        cur = self.con.execute(
            "SELECT * FROM trades WHERE symbol = ? ORDER BY ts ASC LIMIT ?",
            (symbol, int(limit)),
        )
        return [_row_to_dict(r) for r in cur.fetchall()]

    # === Расчёты PnL на лету (long-only FIFO, best-effort) ==================

    def _iter_fifo_closes(self, rows: List[Dict[str, Any]]) -> List[Tuple[float, float]]:
        """
        Возвращает список кортежей (pnl_quote, notional_quote) для каждой «закрывающей» ноги.
        Используем простейшую FIFO-модель long-only.
        """
        pos_size = Decimal("0")
        avg_cost = Decimal("0")
        result: List[Tuple[float, float]] = []

        for r in rows:
            side = str(r.get("side") or "").lower()
            sz = _to_dec(r.get("size"))
            px = _to_dec(r.get("price"))

            if side == "buy":
                # обновляем среднюю цену и объём
                new_notional = px * sz
                total_notional = avg_cost * pos_size + new_notional
                pos_size = pos_size + sz
                if pos_size > 0:
                    avg_cost = total_notional / pos_size
                else:
                    avg_cost = Decimal("0")

            elif side == "sell":
                if sz <= 0:
                    continue
                # закрывающая нога — считаем реализованный pnl по проданной части
                close_size = min(sz, pos_size) if pos_size > 0 else Decimal("0")
                if close_size > 0 and avg_cost > 0:
                    pnl_quote = (px - avg_cost) * close_size
                    notional_quote = avg_cost * close_size
                    result.append((float(pnl_quote), float(notional_quote)))
                    pos_size = pos_size - close_size
                    if pos_size <= 0:
                        pos_size = Decimal("0")
                        avg_cost = Decimal("0")
                # если pos_size == 0, игнорируем «лишнюю» продажу (нет шорта в модели)
        return result

    def last_closed_pnls(self, n: int = 3) -> List[float]:
        """
        Последние n PnL% закрывающих ног по всем символам (в порядке времени).
        Если данных нет — пустой список.
        """
        cur = self.con.execute("SELECT * FROM trades ORDER BY ts ASC")
        rows = [_row_to_dict(r) for r in cur.fetchall()]

        # группируем по символу, сводим, объединяем результаты по времени
        # (упрощённо: сводим всё в один поток — этого достаточно для правил риска)
        pnls_pct: List[float] = []
        by_sym: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            by_sym.setdefault(r["symbol"], []).append(r)

        for sym, items in by_sym.items():
            closes = self._iter_fifo_closes(items)
            for pnl_q, notional_q in closes:
                if notional_q > 0:
                    pnls_pct.append(100.0 * pnl_q / notional_q)

        # берём последние n
        return pnls_pct[-int(n):] if n > 0 else pnls_pct

    def get_realized_pnl(self, days: int = 7) -> float:
        """
        Суммарный реализованный PnL% за последние `days` суток по всем символам.
        Считаем как 100 * sum(pnl_quote) / sum(notional_quote) по закрывающим ногам в окне.
        Если данных нет — 0.0
        """
        if days <= 0:
            return 0.0

        # окно по времени
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        cur = self.con.execute(
            "SELECT * FROM trades WHERE ts >= ? ORDER BY ts ASC",
            (cutoff,),
        )
        rows = [_row_to_dict(r) for r in cur.fetchall()]

        total_pnl = 0.0
        total_notional = 0.0

        by_sym: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            by_sym.setdefault(r["symbol"], []).append(r)

        for sym, items in by_sym.items():
            closes = self._iter_fifo_closes(items)
            for pnl_q, notional_q in closes:
                total_pnl += pnl_q
                total_notional += notional_q

        if total_notional <= 0:
            return 0.0
        return 100.0 * (total_pnl / total_notional)
