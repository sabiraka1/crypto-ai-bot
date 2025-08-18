# src/crypto_ai_bot/market_context/indicators/btc_dominance.py
from __future__ import annotations
from typing import Any, Optional


def fetch_btc_dominance(http: Any, breaker: Any, url: str, *, timeout: float = 2.0) -> Optional[float]:
    """
    Coingecko Global API по умолчанию:
      GET https://api.coingecko.com/api/v3/global
      -> data.market_cap_percentage.btc (проценты)
    Возвращаем долю 0..1 (0.523 = 52.3%).
    """
    if not url:
        return None
    try:
        def _call():
            return http.get_json(url, timeout=timeout)
        data = breaker.call(_call, key="ctx.btc_dominance", timeout=timeout + 0.5)
    except Exception:
        return None

    try:
        pct = float(((data or {}).get("data") or {}).get("market_cap_percentage", {}).get("btc"))
        return max(0.0, min(1.0, pct / 100.0))
    except Exception:
        return None
