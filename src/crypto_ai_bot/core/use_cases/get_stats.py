from __future__ import annotations
from typing import Any, Dict, List, Optional, Callable
from decimal import Decimal

def _get_field(obj: Any, names: list[str], default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        for n in names:
            if n in obj:
                return obj[n]
        return default
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default

def _get_positions(repo) -> list:
    if repo is None:
        return []
    for name in ("get_open", "list_open", "get_snapshot", "get_all_open"):
        fn = getattr(repo, name, None)
        if callable(fn):
            try:
                res = fn()
                if res is None:
                    return []
                return list(res)
            except Exception:
                return []
    return []

def _get_recent_trades(repo, limit: int = 20) -> list:
    if repo is None:
        return []
    for name in ("list_recent", "recent", "list_by_symbol"):
        fn = getattr(repo, name, None)
        if callable(fn):
            try:
                # list_by_symbol may require a symbol; we try without
                import inspect
                sig = inspect.signature(fn)
                if len(sig.parameters) == 0:
                    return list(fn()) or []
                elif len(sig.parameters) == 1:
                    # fallback: unknown symbol -> return empty
                    return []
                elif len(sig.parameters) == 2:
                    return list(fn("*", limit)) or []
            except Exception:
                return []
    return []

def get_stats(cfg, broker, positions_repo=None, trades_repo=None) -> Dict[str, Any]:
    """Aggregate lightweight trading stats. Safe in paper/backtest. 
    Works with partial repositories (returns zeros instead of crashing).
    """
    positions = _get_positions(positions_repo)
    sym_prices: dict[str, Decimal] = {}
    items: list[dict] = []

    total_exposure = Decimal("0")
    total_unreal = Decimal("0")

    for p in positions:
        sym = _get_field(p, ["symbol","sym","pair"], default=cfg.SYMBOL)
        qty = Decimal(str(_get_field(p, ["qty","quantity","size","amount"], default="0")))
        avg_price = Decimal(str(_get_field(p, ["avg_price","avg","price"], default="0")))

        # fetch price per symbol once
        if sym not in sym_prices:
            try:
                t = broker.fetch_ticker(sym) if broker else {"last": 0}
                sym_prices[sym] = Decimal(str(t.get("last") or t.get("close") or 0))
            except Exception:
                sym_prices[sym] = Decimal("0")

        price = sym_prices[sym]
        exposure = abs(qty) * price
        unreal = (price - avg_price) * qty  # sign by qty

        total_exposure += exposure
        total_unreal += unreal

        items.append({
            "symbol": sym,
            "qty": str(qty),
            "avg_price": str(avg_price),
            "price": str(price),
            "exposure": str(exposure),
            "unrealized": str(unreal),
        })

    trades = _get_recent_trades(trades_repo, limit=20)

    return {
        "positions_open": len(items),
        "exposure_value": str(total_exposure),
        "pnl_unrealized": str(total_unreal),
        "positions": items,
        "prices": {k: str(v) for k,v in sym_prices.items()},
        "recent_trades_count": len(trades),
    }
