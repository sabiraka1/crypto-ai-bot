from __future__ import annotations
from typing import Any, Dict, List, Optional
from decimal import Decimal
import time
import inspect

# ---------------- internal helpers ----------------

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

def _safe_dec(x: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(default)

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
    for name in ("list_recent", "recent"):
        fn = getattr(repo, name, None)
        if callable(fn):
            try:
                return list(fn(limit)) if len(inspect.signature(fn).parameters) == 1 else list(fn())
            except Exception:
                return []
    # fallback: some repos expose list_by_symbol(symbol, limit)
    fn = getattr(repo, "list_by_symbol", None)
    if callable(fn):
        try:
            return list(fn("*", limit))
        except Exception:
            return []
    return []

def _list_trades_since(repo, since_ts: int, *, symbol: Optional[str] = None) -> list:
    """Best-effort 'since' query across possible repo APIs."""
    if repo is None:
        return []
    # Preferred: list_since(since_ts) or list_between(start, end[, symbol])
    fn = getattr(repo, "list_since", None)
    if callable(fn):
        try:
            sig = inspect.signature(fn)
            if len(sig.parameters) == 1:
                return list(fn(since_ts)) or []
            elif len(sig.parameters) == 2 and symbol is not None:
                return list(fn(symbol, since_ts)) or []
        except Exception:
            pass
    fn = getattr(repo, "list_between", None)
    if callable(fn):
        try:
            now = int(time.time())
            sig = inspect.signature(fn)
            if len(sig.parameters) == 2:
                return list(fn(since_ts, now)) or []
            elif len(sig.parameters) == 3 and symbol is not None:
                return list(fn(symbol, since_ts, now)) or []
        except Exception:
            pass
    # Fallback: list_recent with large limit
    fn = getattr(repo, "list_recent", None)
    if callable(fn):
        try:
            return list(fn(1000)) or []
        except Exception:
            pass
    return []

def _compute_realized_pnl(trades: list) -> Decimal:
    """Best-effort realized PnL aggregator.
    If trade has 'pnl' or 'profit', we sum them; otherwise 0.
    """
    total = Decimal("0")
    for t in trades:
        pnl = _get_field(t, ["pnl", "profit", "realized_pnl"], default="0")
        total += _safe_dec(pnl, "0")
    return total

# ---------------- public API ----------------

def get_stats(
    cfg,
    broker,
    *,
    positions_repo=None,
    trades_repo=None,
    symbol: Optional[str] = None,
    window_days: int = 1,
) -> Dict[str, Any]:
    """Aggregate lightweight trading stats with optional windowed realized PnL.
    - Works even without repositories (returns zeros).
    - Uses broker for current prices (cached per-symbol within one call).
    - window_days: 1/7/30 ... (>=1)
    """
    symbol = symbol or cfg.SYMBOL
    window_days = max(1, int(window_days))

    positions = _get_positions(positions_repo)
    sym_prices: dict[str, Decimal] = {}
    items: list[dict] = []

    total_exposure = Decimal("0")
    total_unreal = Decimal("0")
    exposure_by_symbol: dict[str, Decimal] = {}

    for p in positions:
        sym = _get_field(p, ["symbol","sym","pair"], default=symbol)
        qty = _safe_dec(_get_field(p, ["qty","quantity","size","amount"], default="0"))
        avg_price = _safe_dec(_get_field(p, ["avg_price","avg","price"], default="0"))

        # fetch price per symbol once
        if sym not in sym_prices:
            try:
                t = broker.fetch_ticker(sym) if broker else {"last": 0}
                sym_prices[sym] = _safe_dec(t.get("last") or t.get("close") or 0)
            except Exception:
                sym_prices[sym] = Decimal("0")

        price = sym_prices[sym]
        exposure = abs(qty) * price
        unreal = (price - avg_price) * qty  # sign by qty

        total_exposure += exposure
        total_unreal += unreal
        exposure_by_symbol[sym] = exposure_by_symbol.get(sym, Decimal("0")) + exposure

        items.append({
            "symbol": sym,
            "qty": str(qty),
            "avg_price": str(avg_price),
            "price": str(price),
            "exposure": str(exposure),
            "unrealized": str(unreal),
        })

    # recent trades (short list)
    trades_recent = _get_recent_trades(trades_repo, limit=20)

    # windowed trades
    since_ts = int(time.time()) - window_days * 86400
    trades_window = _list_trades_since(trades_repo, since_ts, symbol=symbol)
    realized_pnl_window = _compute_realized_pnl(trades_window)

    # top symbols by exposure
    top_symbols = sorted(
        [{"symbol": s, "exposure": str(v)} for s, v in exposure_by_symbol.items()],
        key=lambda x: Decimal(x["exposure"]),
        reverse=True,
    )[:5]

    return {
        "positions_open": len(items),
        "exposure_value": str(total_exposure),
        "pnl_unrealized": str(total_unreal),
        "positions": items,
        "prices": {k: str(v) for k,v in sym_prices.items()},
        "recent_trades_count": len(trades_recent),
        "window_days": window_days,
        "realized_pnl_window": str(realized_pnl_window),
        "trades_window_count": len(trades_window),
        "top_symbols": top_symbols,
    }
