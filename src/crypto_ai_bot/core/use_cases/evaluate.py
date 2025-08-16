from __future__ import annotations
from typing import Dict, Any

from crypto_ai_bot.core.signals import policy

def evaluate(cfg, broker, *, symbol: str, timeframe: str, limit: int, **kwargs) -> Dict[str, Any]:
    """
    Evaluate decision without execution.
    Optional kwargs can pass repositories for richer context:
      - positions_repo
      - trades_repo
      - snapshots_repo
    """
    return policy.decide(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **kwargs)
