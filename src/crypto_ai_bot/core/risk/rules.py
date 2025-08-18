from __future__ import annotations
import sqlite3
import time
from typing import Optional, Dict, Any, List, Tuple

__all__ = [
    "risk_concurrent_positions_blocked",
    "realized_pnl_since_ms",
    "risk_daily_loss_blocked",
    # алиасы для обратной совместимости
    "max_concurrent_positions_blocked",
    "daily_loss_blocked",
]


# ---------- helpers ----------

def _now_ms() -> int:
    return int(time.time() * 1000)

def _start_of_utc_day_ms(now_ms: Optional[int] = None) -> int:
    """
    Начало текущего UTC-дня в миллисекундах.
    Делается целочисленным делением по размеру суток.
    """
    if now_ms is None:
        now_ms = _now_ms()
    day = 24 * 3600 * 1000
    return (now_ms // day) * day


# ---------- правила риска ----------

def risk_concurrent_positions_blocked(positions_repo: Any, *, limit: Optional[int]) -> bool:
    """
    True -> достигнут/превышен лимит открытых позиций.
    Безопасное поведение при ошибках репозитория: блокируем.
    """
    if not limit or int(limit) <= 0:
        return False
    try:
        rows = positions_repo.get_open()
        return len(rows) >= int(limit)
    except Exception:
        return True


def realized_pnl_since_ms(con: sqlite3.Connection, since_ms: int, symbol: Optional[str] = None) -> float:
    """
    Реализованный PnL, накопленный с момента `since_ms` (UTC).
    Корректно учитывает историю ДО since_ms для средней цены инвентаря,
    но суммирует PnL только для SELL, у которых ts >= since_ms.
    """
    if symbol:
        cur = con.execute(
            "SELECT ts, symbol, side, price, qty, COALESCE(fee_amt,0.0) "
            "FROM trades WHERE state='filled' AND symbol=? ORDER BY ts ASC",
            (symbol,),
        )
    else:
        cur = con.execute(
            "SELECT ts, symbol, side, price, qty, COALESCE(fee_amt,0.0) "
            "FROM trades WHERE state='filled' ORDER BY ts ASC"
        )

    rows: List[Tuple[int, str, str, float, float, float]] = [
        (int(ts), str(sym), str(side), float(px), float(q), float(fee))
        for (ts, sym, side, px, q, fee) in cur.fetchall()
    ]
    if not rows:
        return 0.0

    inv: Dict[str, Dict[str, float]] = {}  # per-symbol: {"qty": q, "avg": p}
    realized = 0.0

    for ts, sym, side, px, qty, fee in rows:
        state = inv.setdefault(sym, {"qty": 0.0, "avg": 0.0})
        if side.lower() == "buy":
            new_qty = state["qty"] + qty
            if new_qty <= 0:
                state["qty"] = 0.0
                state["avg"] = 0.0
            else:
                state["avg"] = (
                    (state["avg"] * state["qty"] + px * qty) / new_qty
                    if state["qty"] > 0
                    else px
                )
                state["qty"] = new_qty
        else:
            sell_qty = min(qty, state["qty"]) if state["qty"] > 0 else qty
            pnl = (px - state["avg"]) * sell_qty - fee
            if ts >= since_ms:
                realized += pnl
            state["qty"] = max(0.0, state["qty"] - sell_qty)
            if state["qty"] == 0.0:
                state["avg"] = 0.0

    return float(realized)


def risk_daily_loss_blocked(
    con: sqlite3.Connection, *, max_daily_loss_usd: Optional[float], symbol: Optional[str] = None
) -> bool:
    """
    True -> дневной реализованный убыток (UTC) превысил лимит.
    """
    if not max_daily_loss_usd or float(max_daily_loss_usd) <= 0:
        return False
    sod = _start_of_utc_day_ms()
    pnl_today = realized_pnl_since_ms(con, sod, symbol=symbol)
    return pnl_today <= -float(max_daily_loss_usd)


# ---------- алиасы для обратной совместимости ----------

# Если где-то в коде или тестах использовались старые имена —
# оставим их как синонимы, чтобы ничего не сломать.
max_concurrent_positions_blocked = risk_concurrent_positions_blocked
daily_loss_blocked = risk_daily_loss_blocked
