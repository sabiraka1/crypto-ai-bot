# src/crypto_ai_bot/core/signals/_fusion.py
from __future__ import annotations

def _clip01(x: float) -> float:
    if x is None:
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)

def fuse(rule_score: float | None, ai_score: float | None, cfg) -> float:
    """Веса берём из Settings: DECISION_RULE_WEIGHT / DECISION_AI_WEIGHT (и совместимость со старыми SCORE_*)."""
    w_rule = float(getattr(cfg, "DECISION_RULE_WEIGHT", getattr(cfg, "SCORE_RULE_WEIGHT", 0.7)))
    w_ai = float(getattr(cfg, "DECISION_AI_WEIGHT", getattr(cfg, "SCORE_AI_WEIGHT", 0.3)))
    total_w = max(1e-9, w_rule + w_ai)

    r = _clip01(0.5 if rule_score is None else rule_score)
    a = _clip01(0.5 if ai_score is None else ai_score)
    return _clip01((r * w_rule + a * w_ai) / total_w)
