# -*- coding: utf-8 -*-
"""
Entry policy: decide buy/sell/hold given features and fused scores.
Path: src/crypto_ai_bot/signals/entry_policy.py
"""
from __future__ import annotations
from typing import Dict


def decide(cfg, features: Dict, fused: Dict) -> Dict[str, object]:
    ind = (features or {}).get("indicators") or {}
    price = float(ind.get("price") or 0.0)
    ema20 = float(ind.get("ema20") or 0.0)
    ema50 = float(ind.get("ema50") or 0.0)
    rsi_v = float(ind.get("rsi") or 50.0)
    macd_hist = float(ind.get("macd_hist") or 0.0)

    if price <= 0:
        return {"action": "hold", "reason": "no price", "score": 0.0}

    entry = float(fused.get("entry_score") or 0.0)
    min_score = float(getattr(cfg, "MIN_SCORE_TO_BUY", 0.65))
    rsi_crit = float(getattr(cfg, "RSI_CRITICAL", 90.0))

    # simple directional checks
    bullish = (ema20 > ema50 and macd_hist > 0 and rsi_v < rsi_crit)
    bearish = (ema20 < ema50 and macd_hist < 0 and (100 - rsi_v) < rsi_crit)

    if entry >= min_score and bullish:
        return {"action": "buy", "reason": f"entry={entry:.2f} bullish trend", "score": entry}
    if entry >= min_score and bearish:
        return {"action": "sell", "reason": f"entry={entry:.2f} bearish trend", "score": entry}

    return {"action": "hold", "reason": f"entry={entry:.2f} not strong enough", "score": entry}







