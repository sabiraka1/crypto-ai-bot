# src/crypto_ai_bot/market_context/indicators/fear_greed.py
from __future__ import annotations
from typing import Any, Optional


def fetch_fear_greed(http: Any, breaker: Any, url: str, *, timeout: float = 2.0) -> Optional[float]:
    """
    Alternative.me FNG API:
      GET https://api.alternative.me/fng/?limit=1
      -> data[0].value (строка "0..100")
    Возвращаем 0..1 (например, 0.73).
    """
    if not url:
        return None
    try:
        def _call():
            return http.get_json(url, timeout=timeout)
        data = breaker.call(_call, key="ctx.fng", timeout=timeout + 0.5)
    except Exception:
        return None

    try:
        arr = (data or {}).get("data") or []
        if not arr:
            return None
        v = float(arr[0].get("value"))
        return max(0.0, min(1.0, v / 100.0))
    except Exception:
        return None
