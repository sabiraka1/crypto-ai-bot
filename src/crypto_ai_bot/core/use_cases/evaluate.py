from __future__ import annotations

from typing import Any, Dict, Optional

from crypto_ai_bot.core.signals import policy

def _ensure_explain(decision: Dict[str, Any]) -> Dict[str, Any]:
    ex = decision.get("explain")
    if not isinstance(ex, dict):
        ex = {}
        decision["explain"] = ex
    ex.setdefault("signals", {})
    ex.setdefault("blocks", {})
    ex.setdefault("weights", {})
    ex.setdefault("thresholds", {})
    ex.setdefault("context", {})
    return ex

def evaluate(cfg, broker, *, symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: int = 300, risk_reason: Optional[str] = None, **repos) -> Dict[str, Any]:
    """
    Вычисляет торговое решение (без исполнения).
    Дополнительно может принять risk_reason и поместить его в Decision.explain['blocks']['risk'] для прозрачности.
    """
    sym = symbol or cfg.SYMBOL
    tf = timeframe or cfg.TIMEFRAME

    decision = policy.decide(cfg, broker, symbol=sym, timeframe=tf, limit=limit, **repos)

    # гарантируем, что базовые поля присутствуют
    decision.setdefault("symbol", sym)
    decision.setdefault("timeframe", tf)

    # Прозрачность риска: если известна причина блокировки — прокинем её в explain.blocks.risk
    if risk_reason:
        ex = _ensure_explain(decision)
        ex["blocks"]["risk"] = {"reason": str(risk_reason)}
    return decision
