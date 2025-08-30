from __future__ import annotations
from typing import Optional, Dict, Any
from crypto_ai_bot.utils.decimal import dec

def _per_symbol_key(symbol: str, base: str) -> str:
    s = symbol.replace("/", "_").replace("-", "_")
    return f"{base}_{s}".upper()

def check(storage, symbol: str, settings: Any) -> Optional[Dict[str, str]]:
    # max orders / 5m
    max_orders_5m = int(getattr(settings, "BUDGET_MAX_ORDERS_5M", 0) or 0)
    v = getattr(settings, _per_symbol_key(symbol, "BUDGET_MAX_ORDERS_5M"), None)
    if v not in (None, ""):
        try: max_orders_5m = int(v)
        except Exception: pass
    if max_orders_5m > 0:
        cnt5 = storage.trades.count_orders_last_minutes(symbol, 5)
        if cnt5 >= max_orders_5m:
            return {"type": "max_orders_5m", "count_5m": str(cnt5), "limit": str(int(max_orders_5m))}

    # daily turnover (quote)
    max_turnover = dec(str(getattr(settings, "BUDGET_MAX_TURNOVER_DAY_QUOTE", "0") or "0"))
    v2 = getattr(settings, _per_symbol_key(symbol, "BUDGET_MAX_TURNOVER_DAY_QUOTE"), None)
    if v2 not in (None, ""):
        try: max_turnover = dec(str(v2))
        except Exception: pass
    if max_turnover > 0:
        day_turn = storage.trades.daily_turnover_quote(symbol)
        if day_turn >= max_turnover:
            return {"type": "max_turnover_day", "turnover": str(day_turn), "limit": str(max_turnover)}
    return None
