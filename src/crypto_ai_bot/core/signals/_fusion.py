from __future__ import annotations
from typing import Any, Dict, Tuple

def decide(symbol: str, feat: Dict[str, Any], *, cfg: Any) -> Tuple[str, Dict[str, Any]]:
    """
    Простейшая логика (заглушка):
      - если нет цены → HOLD
      - иначе возвращаем HOLD и explanation
    Реальную стратегию подключим позже (EMA/RSI и т.п.).
    """
    price = float(feat.get("price") or 0.0)
    if price <= 0:
        return "hold", {"reason": "no_price"}

    explain = {"price": price, "score": 0.0, "parts": {}}
    return "hold", explain
