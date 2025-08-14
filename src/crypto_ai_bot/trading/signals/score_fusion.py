# -*- coding: utf-8 -*-
"""
Score fusion: combine rule-based score and (optional) AI score.
Path: src/crypto_ai_bot/signals/score_fusion.py
"""
from __future__ import annotations
from typing import Dict


def fuse_scores(cfg, rule_score: float, ai_score: float | None) -> Dict[str, float | dict]:
    """
    Returns a dict with unified entry score and components.
    ENV / Settings knobs (optional):
      RULE_WEIGHT (default 0.6), AI_WEIGHT (default 0.4)
      ENFORCE_AI_GATE (0|1), AI_MIN_TO_TRADE (0..1)
    """
    try:
        rw = float(getattr(cfg, "RULE_WEIGHT", 0.6))
        aw = float(getattr(cfg, "AI_WEIGHT", 0.4))
    except Exception:
        rw, aw = 0.6, 0.4
    if rw < 0: rw = 0.0
    if aw < 0: aw = 0.0
    if rw + aw == 0:
        rw, aw = 1.0, 0.0
    # normalize to 1
    s = rw + aw
    rw /= s; aw /= s

    rs = float(max(0.0, min(1.0, rule_score)))
    ai = float(max(0.0, min(1.0, ai_score if ai_score is not None else getattr(cfg, "AI_FAILOVER_SCORE", 0.55))))

    # optional hard gate
    gate = int(getattr(cfg, "ENFORCE_AI_GATE", 1)) == 1
    ai_min = float(getattr(cfg, "AI_MIN_TO_TRADE", 0.55))
    if gate and ai < ai_min:
        entry = min(rs, ai)  # conservative
        reason = f"AI gate: {ai:.2f} < {ai_min:.2f}"
    else:
        entry = rw * rs + aw * ai
        reason = "weighted fusion"

    return {
        "entry_score": float(max(0.0, min(1.0, entry))),
        "rule_score": rs,
        "ai_score": ai,
        "explain": {
            "rule_weight": rw,
            "ai_weight": aw,
            "reason": reason,
        }
    }
