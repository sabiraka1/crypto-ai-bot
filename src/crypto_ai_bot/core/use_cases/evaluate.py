# src/crypto_ai_bot/core/use_cases/evaluate.py
from __future__ import annotations

from typing import Any, Dict

from crypto_ai_bot.core.signals.policy import decide
from crypto_ai_bot.utils import metrics


def evaluate(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    Вычислить торговое решение без исполнения ордеров.
    Источник истины по логике — core.signals.policy.decide(...)
    """
    decision = decide(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    action = str(decision.get("action", "hold")).lower()
    metrics.inc("bot_decision_total", {"action": action})
    return decision
