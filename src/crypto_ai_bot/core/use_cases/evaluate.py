from __future__ import annotations
from typing import Any, Dict, Optional
from decimal import Decimal
from uuid import uuid4

from crypto_ai_bot.core.signals import policy

def evaluate(cfg, broker, *, symbol: Optional[str], timeframe: Optional[str], limit: Optional[int]) -> Dict[str, Any]:
    """Return decision (dict) with a generated decision_id if missing."""
    res = policy.decide(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    # Normalize structure
    if isinstance(res, dict):
        dec = res
    else:
        # convert dataclass-like to dict
        dec = getattr(res, 'model_dump', lambda: res.__dict__)()
    if 'decision_id' not in dec:
        dec['decision_id'] = uuid4().hex
    return dec
