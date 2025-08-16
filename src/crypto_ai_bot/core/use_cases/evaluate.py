from __future__ import annotations
from typing import Any, Dict, Optional
from crypto_ai_bot.core.signals import policy
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.rate_limit import rate_limit

@rate_limit(
    calls=6, period=10.0,
    calls_attr="RL_EVALUATE_CALLS", period_attr="RL_EVALUATE_PERIOD",
    key_fn=lambda *a, **kw: f"evaluate:{getattr(a[0],'MODE',None)}:{kw.get('symbol') or getattr(a[0],'SYMBOL','')}:{kw.get('timeframe') or getattr(a[0],'TIMEFRAME','')}",
)
def evaluate(cfg, broker, *, symbol: Optional[str]=None, timeframe: Optional[str]=None, limit: int=300, **repos) -> Dict[str, Any]:
    """Возвращает decision без исполнения."""
    sym = symbol or cfg.SYMBOL
    tf = timeframe or cfg.TIMEFRAME
    dec = policy.decide(cfg, broker, symbol=sym, timeframe=tf, limit=limit, **repos)
    metrics.inc("bot_decision_total", {"action": dec.get("action", "hold")})
    return dec
