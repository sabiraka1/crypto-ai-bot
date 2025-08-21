from __future__ import annotations
from typing import Any, Dict, Tuple
from .base import Decision

class EmaCross:
    """
    Простая стратегия: BUY при ema_fast > ema_slow, SELL при ema_fast < ema_slow, иначе HOLD.
    Требует наличия feat["ind"]["ema_fast"/"ema_slow"] (ставятся в _build, если broker умеет fetch_ohlcv).
    """
    name = "ema_cross"

    def decide(self, symbol: str, feat: Dict[str, Any], *, cfg: Any) -> Tuple[Decision, Dict[str, Any]]:
        ind = feat.get("ind") or {}
        ef = ind.get("ema_fast")
        es = ind.get("ema_slow")
        price = float(feat.get("price") or 0.0)

        if ef is None or es is None or price <= 0:
            return "hold", {"reason": "no_indicators_or_price", "price": price}

        if ef > es:
            return "buy", {"reason": "ema_fast>ema_slow", "ema_fast": ef, "ema_slow": es, "price": price}
        if ef < es:
            return "sell", {"reason": "ema_fast<ema_slow", "ema_fast": ef, "ema_slow": es, "price": price}
        return "hold", {"reason": "ema_fast==ema_slow", "ema_fast": ef, "ema_slow": es, "price": price}
