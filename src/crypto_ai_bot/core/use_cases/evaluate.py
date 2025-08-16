from __future__ import annotations
from typing import Any, Dict, Optional
from crypto_ai_bot.core.signals import policy
from crypto_ai_bot.utils import metrics

def evaluate(cfg, broker, *, symbol: Optional[str]=None, timeframe: Optional[str]=None, limit: Optional[int]=None) -> Dict[str, Any]:
    dec = policy.decide(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    metrics.inc("bot_decision_total", {"action": dec.get("action","hold")})
    metrics.observe("latency_decide_seconds", 0.0)  # заполняется отдельным middleware при желании
    return dec
