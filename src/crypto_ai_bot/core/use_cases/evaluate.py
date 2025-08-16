from __future__ import annotations
from typing import Dict, Any
import json

from crypto_ai_bot.core.signals import policy
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.utils.metrics import inc

def _audit(audit_repo, event_type: str, payload: Dict[str, Any]) -> None:
    if audit_repo is None:
        return
    try:
        if hasattr(audit_repo, "insert"):
            audit_repo.insert(event_type, payload)  # type: ignore
        elif hasattr(audit_repo, "log"):
            audit_repo.log(event_type, payload)  # type: ignore
        elif hasattr(audit_repo, "add"):
            audit_repo.add(event_type, payload)  # type: ignore
        # else: silently ignore
    except Exception:
        pass

def evaluate(cfg, broker, *, symbol: str, timeframe: str, limit: int, **kwargs) -> Dict[str, Any]:
    """
    Evaluate decision without execution.
    Optional kwargs can pass repositories for richer context:
      - positions_repo
      - trades_repo
      - snapshots_repo
      - audit_repo (optional; if present we'll write decision/audit records)
    After decision is computed, run risk checks and annotate decision.explain.blocks
    so that UI (/why) can show what exactly blocked the action.
    """
    decision = policy.decide(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **kwargs)

    ok, reason = risk_manager.check(decision, cfg)
    if not ok:
        # parse "rule: detail" into parts
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
        decision["action"] = "hold"
        try:
            inc("risk_block_total", {"rule": rule_name})
        except Exception:
            pass

    # optional audit
    audit_repo = kwargs.get("audit_repo")
    _audit(audit_repo, "decision", {
        "symbol": decision.get("symbol"),
        "timeframe": decision.get("timeframe"),
        "action": decision.get("action"),
        "score": decision.get("score"),
        "explain": decision.get("explain"),
    })

    return decision
