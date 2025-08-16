from __future__ import annotations
from typing import Dict, Any

from crypto_ai_bot.core.signals import policy
from crypto_ai_bot.core.risk import manager as risk_manager

def evaluate(cfg, broker, *, symbol: str, timeframe: str, limit: int, **kwargs) -> Dict[str, Any]:
    """
    Evaluate decision without execution.
    Optional kwargs can pass repositories for richer context:
      - positions_repo
      - trades_repo
      - snapshots_repo
    After decision is computed, run risk checks and annotate decision.explain.blocks
    so that UI (/why) can show what exactly blocked the action.
    """
    decision = policy.decide(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **kwargs)

    ok, reason = risk_manager.check(decision, cfg)
    if not ok:
        # Try to parse "rule: detail" into parts
        rule_name = "risk"
        detail = reason
        if ":" in reason:
            rule_name, detail = reason.split(":", 1)
            rule_name = rule_name.strip()
            detail = detail.strip()
        exp = decision.get("explain") or {}
        blocks = exp.get("blocks") or {}
        blocks[rule_name] = detail or "blocked"
        exp["blocks"] = blocks
        decision["explain"] = exp
        # Optionally, force hold if blocked
        decision["action"] = "hold"

    return decision
