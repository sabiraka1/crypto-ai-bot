# src/crypto_ai_bot/core/analytics/pnl.py
from __future__ import annotations
from typing import Iterable, Dict, Any, Optional

def realized_pnl_summary(trades: Iterable[Dict[str, Any]], symbol: Optional[str] = None) -> Dict[str, float]:
    """
    Простой кумулятивный PnL по закрытым сделкам (FIFO, long-only).
    Ожидаемые поля трейда: symbol, side ('buy'|'sell'), price, qty.
    Возвращает: {'pnl_abs': ..., 'pnl_pct': ..., 'closed_trades': N}
    """
    cash = 0.0     # вложено (отрицательно при покупках)
    pos_qty = 0.0  # текущая позиция
    pnl = 0.0
    closed = 0

    for t in trades:
        if symbol and str(t.get("symbol")) != symbol:
            continue
        side = str(t.get("side", "")).lower()
        price = float(t.get("price") or 0.0)
        qty = float(t.get("qty") or t.get("amount") or 0.0)
        if qty <= 0 or price <= 0:
            continue

        if side == "buy":
            cash -= price * qty
            pos_qty += qty
        elif side == "sell":
            if pos_qty <= 0:
                continue
            # доля позиции, которую закрываем
            q = min(pos_qty, qty)
            pnl += q * price + cash * (q / max(pos_qty, 1e-9))
            pos_qty -= q
            cash *= (pos_qty / max(pos_qty + q, 1e-9))
            closed += 1

    invested = -cash if cash < 0 else 0.0
    pnl_pct = (pnl / invested * 100.0) if invested > 0 else 0.0
    return {"pnl_abs": float(pnl), "pnl_pct": float(pnl_pct), "closed_trades": int(closed)}
