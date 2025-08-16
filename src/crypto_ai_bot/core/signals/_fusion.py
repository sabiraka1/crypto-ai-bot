# src/crypto_ai_bot/core/signals/_fusion.py
from __future__ import annotations

from typing import Optional


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def fuse(rule_score: Optional[float], ai_score: Optional[float], cfg) -> float:
    """
    Объединяет rule_score и ai_score в итоговый score ∈ [0..1].
    Веса берём из Settings (если нет — дефолты).
    """
    if rule_score is None and ai_score is None:
        return 0.5

    w_rule = float(getattr(cfg, "DECISION_RULE_WEIGHT", 0.7))
    w_ai = float(getattr(cfg, "DECISION_AI_WEIGHT", 0.3))
    s_rule = 0.0 if rule_score is None else float(rule_score)
    s_ai = 0.0 if ai_score is None else float(ai_score)

    # Нормализация весов
    s = w_rule + w_ai
    if s <= 0.0:
        w_rule = 0.7
        w_ai = 0.3
        s = 1.0
    w_rule /= s
    w_ai /= s

    return _clip01(w_rule * s_rule + w_ai * s_ai)
