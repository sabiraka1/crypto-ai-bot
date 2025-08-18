from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class Decision:
    action: str   # 'buy' | 'sell' | 'hold'
    score: float = 0.0
    reason: Optional[str] = None

BUY_TH = 0.6
SELL_TH = -0.6

def decide(signals: Dict[str, float], ctx: Dict[str, Any]) -> Decision:
    """
    Бейзлайн: агрегируем нормированные признаки ([-1..+1]) простым взвешенным суммированием.
    ctx может передать веса/порог из Settings.
    """
    if not signals:
        return Decision("hold", 0.0, "no_signals")
    w = ctx.get("weights") or {}
    score = 0.0
    for k, v in signals.items():
        score += float(v) * float(w.get(k, 1.0))
    buy_th = float(ctx.get("BUY_THRESHOLD", BUY_TH))
    sell_th = float(ctx.get("SELL_THRESHOLD", SELL_TH))
    if score >= buy_th:
        return Decision("buy", score, "score>=buy_th")
    if score <= sell_th:
        return Decision("sell", score, "score<=sell_th")
    return Decision("hold", score, "in_band")
