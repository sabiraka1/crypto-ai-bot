from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from typing import List, Tuple

from ...storage.facade import Storage


def _today_bounds_ms() -> tuple[int, int]:
    now = _dt.datetime.utcnow()
    start = _dt.datetime(now.year, now.month, now.day)
    start_ms = int(start.timestamp() * 1000)
    end_ms = start_ms + 24 * 60 * 60 * 1000
    return start_ms, end_ms


def _fetch_today_trades(storage: Storage, symbol: str) -> List[tuple[str, Decimal, Decimal]]:
    cur = storage.conn.cursor()
    a, b = _today_bounds_ms()
    rows = cur.execute(
        "SELECT side, amount, cost FROM trades WHERE symbol=? AND ts_ms>=? AND ts_ms<? ORDER BY ts_ms ASC",
        (symbol, a, b),
    ).fetchall()
    out: List[Tuple[str, Decimal, Decimal]] = []
    for side, amt, cost in rows:
        out.append((str(side), Decimal(str(amt)), Decimal(str(cost))))
    return out


def _fifo_closed_pnls_today(storage: Storage, symbol: str) -> List[Decimal]:
    trades = _fetch_today_trades(storage, symbol)
    lots: List[Tuple[Decimal, Decimal]] = []
    pnls: List[Decimal] = []
    for side, amt, cost in trades:
        if side == "buy":
            lots.append((amt, cost))
        elif side == "sell":
            remain = amt
            alloc = Decimal("0")
            while remain > 0 and lots:
                b_amt, b_cost = lots[0]
                if b_amt <= remain:
                    alloc += b_cost
                    remain -= b_amt
                    lots.pop(0)
                else:
                    ratio = (remain / b_amt)
                    alloc += (b_cost * ratio)
                    lots[0] = (b_amt - remain, b_cost * (Decimal("1") - ratio))
                    remain = Decimal("0")
            pnls.append(cost - alloc)
    return pnls


def compute_today_loss_streak(storage: Storage, symbol: str) -> int:
    """Вернуть длину текущей серии подряд убыточных закрытий за сегодня."""
    pnls = _fifo_closed_pnls_today(storage, symbol)
    streak = 0
    for p in reversed(pnls):
        if p < 0:
            streak += 1
        else:
            break
    return streak
