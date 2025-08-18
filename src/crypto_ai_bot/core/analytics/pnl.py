from __future__ import annotations
import sqlite3
from typing import Dict, Optional, Tuple

def realized_pnl_summary(con: sqlite3.Connection, symbol: Optional[str] = None) -> Dict[str, float|int]:
    """
    PnL только по закрытым сделкам (state='filled'), с учётом комиссий.
    """
    if symbol:
        cur = con.execute(
            "SELECT symbol, side, price, qty, COALESCE(fee_amt,0.0) "
            "FROM trades WHERE state='filled' AND symbol=? ORDER BY ts ASC", (symbol,)
        )
    else:
        cur = con.execute(
            "SELECT symbol, side, price, qty, COALESCE(fee_amt,0.0) "
            "FROM trades WHERE state='filled' ORDER BY ts ASC"
        )
    rows = [(str(sym), str(side), float(price), float(qty), float(fee))
            for (sym, side, price, qty, fee) in cur.fetchall()]
    if not rows:
        return {"closed_trades": 0, "wins": 0, "losses": 0, "pnl_abs": 0.0, "pnl_pct": 0.0}

    inv: Dict[str, Dict[str, float]] = {}
    realized = 0.0
    realized_cost = 0.0
    wins = losses = closed = 0

    for sym, side, px, qty, fee in rows:
        s = inv.setdefault(sym, {"qty": 0.0, "avg": 0.0})
        if side == "buy":
            new_qty = s["qty"] + qty
            if new_qty <= 0:
                s["qty"] = 0.0; s["avg"] = 0.0
            else:
                s["avg"] = (s["avg"] * s["qty"] + px * qty) / new_qty if s["qty"] > 0 else px
                s["qty"] = new_qty
        else:
            sell_qty = min(qty, s["qty"]) if s["qty"] > 0 else qty
            pnl = (px - s["avg"]) * sell_qty - fee
            realized += pnl
            realized_cost += s["avg"] * sell_qty
            closed += 1
            if pnl >= 0: wins += 1
            else: losses += 1
            s["qty"] = max(0.0, s["qty"] - sell_qty)
            if s["qty"] == 0.0:
                s["avg"] = 0.0

    pnl_pct = (realized / realized_cost * 100.0) if realized_cost > 0 else 0.0
    return {"closed_trades": closed, "wins": wins, "losses": losses, "pnl_abs": realized, "pnl_pct": pnl_pct}
