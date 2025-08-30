from __future__ import annotations
from typing import Optional, Dict, Any
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.settings_keys import per_symbol_override

def check(storage, symbol: str, settings: Any) -> Optional[Dict[str, str]]:
    # max orders / 5m
    max_orders_5m = per_symbol_override(settings, symbol, "BUDGET_MAX_ORDERS_5M", lambda s: int(float(s)), 0)
    if max_orders_5m > 0:
        cnt5 = storage.trades.count_orders_last_minutes(symbol, 5)
        if cnt5 >= max_orders_5m:
            return {"type": "max_orders_5m", "count_5m": str(cnt5), "limit": str(int(max_orders_5m))}
    # daily turnover (quote)
    max_turnover = per_symbol_override(settings, symbol, "BUDGET_MAX_TURNOVER_DAY_QUOTE", lambda s: dec(s), dec("0"))
    if max_turnover > 0:
        day_turn = storage.trades.daily_turnover_quote(symbol)
        if day_turn >= max_turnover:
            return {"type": "max_turnover_day", "turnover": str(day_turn), "limit": str(max_turnover)}
    return None
