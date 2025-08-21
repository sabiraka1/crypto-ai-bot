from __future__ import annotations
from typing import Any, Dict, Tuple
from .base import Decision, IStrategy
from .ema_cross import EmaCross

# Фоллбэк на старую политику (держим совместимость)
from crypto_ai_bot.core.signals._fusion import decide as fallback_decide

_STRATS: dict[str, IStrategy] = {
    "ema_cross": EmaCross(),
}

def decide(symbol: str, feat: Dict[str, Any], *, cfg: Any) -> Tuple[Decision, Dict[str, Any]]:
    name = str(getattr(cfg, "STRATEGY", "hold")).lower()
    strat = _STRATS.get(name)
    if strat:
        return strat.decide(symbol, feat, cfg=cfg)
    # "hold" или неизвестное имя стратегии — используем прежнюю политику
    return fallback_decide(symbol, feat, cfg=cfg)
