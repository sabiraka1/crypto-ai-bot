
# -*- coding: utf-8 -*-
"""
crypto_ai_bot.core.signals.validator
-----------------------------------
РњСЏРіРєРёР№ РІР°Р»РёРґР°С‚РѕСЂ РїСЂРёР·РЅР°РєРѕРІ (Phase 4).
- Р“Р°СЂР°РЅС‚РёСЂСѓРµС‚, С‡С‚Рѕ indicators РІРєР»СЋС‡Р°РµС‚: price, ema20, ema50, rsi, macd_hist, atr, atr_pct
- Р”РѕР·Р°РїРѕР»РЅСЏРµС‚ atr/atr_pct РЅР° РѕСЃРЅРѕРІРµ С†РµРЅС‹, РµСЃР»Рё РѕРґРЅРѕ РёР· РЅРёС… РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚.
- РќРРљРћР“Р”Рђ РЅРµ Р±СЂРѕСЃР°РµС‚ РёСЃРєР»СЋС‡РµРЅРёРµ, РІРѕР·РІСЂР°С‰Р°РµС‚ РёСЃРїСЂР°РІР»РµРЅРЅС‹Р№ СЃР»РѕРІР°СЂСЊ.

РСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ:
    fs = validate(fs)
"""
from __future__ import annotations

from typing import Dict, Any


_REQUIRED = ("price", "ema20", "ema50", "rsi", "macd_hist", "atr", "atr_pct")


def _flt(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def validate(features: Dict[str, Any]) -> Dict[str, Any]:
    fs = dict(features or {})
    ind = dict((fs.get("indicators") or {}))

    # 1) Р‘Р°Р·РѕРІС‹Рµ РєР»СЋС‡Рё
    for k in _REQUIRED:
        ind[k] = _flt(ind.get(k), 0.0)

    # 2) РЎРІСЏР·СЊ atr в†” atr_pct
    price = _flt(ind.get("price"), 0.0)
    atr = _flt(ind.get("atr"), 0.0)
    atr_pct = _flt(ind.get("atr_pct"), 0.0)

    if atr <= 0.0 and atr_pct > 0.0 and price > 0.0:
        atr = atr_pct * price / 100.0
    elif atr_pct <= 0.0 and atr > 0.0 and price > 0.0:
        atr_pct = (atr / price) * 100.0

    ind["atr"] = atr
    ind["atr_pct"] = atr_pct

    fs["indicators"] = ind
    # РќРѕСЂРјРёСЂСѓРµРј rule_score
    try:
        rs = float(fs.get("rule_score", 0.0))
    except Exception:
        rs = 0.0
    fs["rule_score"] = 0.0 if rs < 0 else 1.0 if rs > 1.0 else rs

    # ai_score РѕРїС†РёРѕРЅР°Р»РµРЅ; РµСЃР»Рё РµСЃС‚СЊ вЂ” clamp
    if "ai_score" in fs:
        try:
            ai = float(fs.get("ai_score"))
        except Exception:
            ai = 0.0
        fs["ai_score"] = 0.0 if ai < 0 else 1.0 if ai > 1.0 else ai

    # market.condition РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ
    market = dict(fs.get("market") or {})
    if "condition" not in market or not market["condition"]:
        market["condition"] = "unknown"
    fs["market"] = market

    return fs






