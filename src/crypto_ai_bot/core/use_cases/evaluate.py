from __future__ import annotations
from typing import Dict, Any
from crypto_ai_bot.core.signals import policy

def evaluate(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    return policy.decide(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)