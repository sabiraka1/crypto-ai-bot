import sqlite3
from typing import Dict, List, Any, Optional


class SqlitePositionRepository:
    """
    Позиции считаются по заполненным сделкам (state='filled') в таблице trades.
    Модель: усреднённая стоимость (average cost). Для sell уменьшаем qty; если qty упал до 0 — сбрасываем среднюю.
    Никаких дополнительных таблиц не требуется.
    """

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        # Индексы на trades создаются миграторами; здесь только best-effort
        try:
            self.con.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts);")
            self.con.execute("CREATE INDEX IF NOT EXISTS idx_trades_state ON trades(state);")
        except Exception:
            pass

    # ---------- публичные методы, используемые в коде ----------

    def has_long(self, symbol: str) -> bool:
        """Есть ли открытая long-позиция по символу (qty > 0)."""
        return self.long_qty(symbol) > 0.0

    def long_qty(self, symbol: str) -> float:
        """Текущий объём открытой long-позиции по символу."""
        pos = self._compute_positions(symbol_only=symbol)
        p = pos.get(symbol)
        return float(p["qty"]) if p else 0.0

    def get_open(self) -> List[Dict[str, Any]]:
        """
        Список открытых позиций (qty > 0) по всем символам.
        Формат: {'symbol', 'qty', 'avg_price', 'entry_ts'}
        """
        pos = self._compute_positions(symbol_only=None)
        out = []
        for sym, p in pos.items():
            if p["qty"] > 0:
                out.append(
                    {
                        "symbol": sym,
                        "qty": float(p["qty"]),
                        "avg_price": float(p["avg_price"]) if p["avg_price"] is not None else None,
                        "entry_ts": int(p["entry_ts"]) if p["entry_ts"] is not None else None,
                    }
                )
        return out

    # ---------- внутренняя логика ----------

    def _compute_positions(self, symbol_only: Optional[str]) -> Dict[str, Dict[str, Any]]:
        """
        Проходит по заполненным сделкам по возрастанию времени и считает остаток qty и среднюю цену.
        Для каждой покупки: avg = (avg*qty + price*buy_qty) / (qty + buy_qty)
        Для продажи: qty = max(0, qty - sell_qty); если qty == 0, avg = 0, entry_ts = None
        """
        params: List[Any] = []
        q = (
            "SELECT ts, symbol, side, price, qty "
            "FROM trades WHERE state='filled' "
        )
        if symbol_only:
            q += "AND symbol=? "
            params.append(symbol_only)
        q += "ORDER BY symbol ASC, ts ASC"

        cur = self.con.execute(q, tuple(params))
        pos: Dict[str, Dict[str, Any]] = {}

        for ts, symbol, side, price, qty in cur.fetchall():
            p = pos.get(symbol)
            if p is None:
                p = {"qty": 0.0, "avg_price": 0.0, "entry_ts": None}
                pos[symbol] = p

            if side == "buy":
                new_qty = p["qty"] + float(qty)
                if new_qty <= 0:
                    # теоретически невозможно, но на всякий случай
                    p["qty"] = 0.0
                    p["avg_price"] = 0.0
                    p["entry_ts"] = None
                else:
                    # усреднение
                    p["avg_price"] = (p["avg_price"] * p["qty"] + float(price) * float(qty)) / new_qty if p["qty"] > 0 else float(price)
                    p["qty"] = new_qty
                    if p["entry_ts"] is None:
                        p["entry_ts"] = int(ts)
            else:  # 'sell'
                new_qty = p["qty"] - float(qty)
                if new_qty <= 0:
                    # позиция закрыта
                    p["qty"] = 0.0
                    p["avg_price"] = 0.0
                    p["entry_ts"] = None
                else:
                    p["qty"] = new_qty
                    # средняя цена остаётся прежней (average cost)
        return pos
