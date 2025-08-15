# -*- coding: utf-8 -*-
"""
Signal validation helpers.
Path: src/crypto_ai_bot/signals/signal_validator.py
"""
from __future__ import annotations
from typing import Dict, List, Tuple


REQUIRED_KEYS = ("price", "ema20", "ema50", "rsi", "macd_hist", "atr")


def validate_features(cfg, features: Dict) -> tuple[bool, list[str]]:
    problems: List[str] = []
    if not isinstance(features, dict):
        return False, ["features is not a dict"]

    ind = features.get("indicators") or {}
    if not isinstance(ind, dict):
        problems.append("indicators missing")
    else:
        for k in REQUIRED_KEYS:
            if k not in ind:
                problems.append(f"indicator {k} missing")
            else:
                try:
                    v = float(ind[k])
                    if v != v:  # NaN
                        problems.append(f"{k} is NaN")
                except Exception:
                    problems.append(f"{k} not numeric")

        price = float(ind.get("price") or 0.0)
        if price <= 0:
            problems.append("price <= 0")

    return (len(problems) == 0), problems






