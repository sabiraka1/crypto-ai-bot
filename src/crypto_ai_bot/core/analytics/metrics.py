from __future__ import annotations
from typing import Any, Iterable

def realized_pnl(trades_repo: Any, symbol: str | None = None) -> float:
    if not trades_repo:
        return 0.0
    if hasattr(trades_repo, "list_realized"):
        rows = trades_repo.list_realized(symbol=symbol)  # [{'pnl_usd': ...}, ...]
        return float(sum((r.get("pnl_usd") or 0) for r in rows))
    if hasattr(trades_repo, "realized_pnl"):
        return float(trades_repo.realized_pnl(symbol=symbol))
    return 0.0

def win_rate(trades_repo: Any, symbol: str | None = None) -> float:
    if not trades_repo or not hasattr(trades_repo, "list_realized"):
        return 0.0
    rows = trades_repo.list_realized(symbol=symbol)
    if not rows:
        return 0.0
    wins = sum(1 for r in rows if (r.get("pnl_usd") or 0) > 0)
    return wins / len(rows)

def max_drawdown(equity_points: Iterable[float]) -> float:
    peak = float("-inf")
    mdd = 0.0
    for x in equity_points:
        if x > peak:
            peak = x
        if peak > 0:
            mdd = max(mdd, (peak - x) / peak)
    return mdd
