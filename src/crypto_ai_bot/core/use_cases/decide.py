from __future__ import annotations
from typing import Any, Dict

from crypto_ai_bot.core.signals.builder import build_signals
from crypto_ai_bot.core.signals.policy import decide, Decision

def evaluate_only(*, cfg, broker, symbol: str) -> Dict[str, Any]:
    """
    Чистая оценка: собираем сигналы -> решение (без place_order).
    Возвращаем компактный dict совместимый с окружением.
    """
    signals = build_signals(cfg=cfg, broker=broker, symbol=symbol)
    ctx = {
        "weights": getattr(cfg, "SIGNAL_WEIGHTS", {}),
        "BUY_THRESHOLD": getattr(cfg, "BUY_THRESHOLD", 0.6),
        "SELL_THRESHOLD": getattr(cfg, "SELL_THRESHOLD", -0.6),
    }
    d = decide(signals, ctx)
    return {"action": d.action, "score": d.score, "reason": d.reason, "signals": signals}
