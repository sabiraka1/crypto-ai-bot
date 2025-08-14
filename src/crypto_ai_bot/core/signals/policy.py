
# -*- coding: utf-8 -*-
"""
crypto_ai_bot.core.signals.policy
---------------------------------
Р•РґРёРЅС‹Р№ entry-policy (Phase 4).
Р¤СѓРЅРєС†РёСЏ decide(features, cfg) РІРѕР·РІСЂР°С‰Р°РµС‚ dict:
  {action: 'buy'|'sell'|'hold', reason: str, score: float}
- РСЃРїРѕР»СЊР·СѓРµС‚ features['rule_score'] Рё (РµСЃР»Рё РµСЃС‚СЊ) features['ai_score'].
- РџСЂРёРјРµРЅСЏРµС‚ РІРѕСЂРѕС‚Р° AI (cfg.ENFORCE_AI_GATE, cfg.AI_MIN_TO_TRADE).
- РџРѕСЂРѕРі РЅР° РїРѕРєСѓРїРєСѓ: cfg.MIN_SCORE_TO_BUY.
- Р”РѕР±Р°РІР»СЏРµС‚ РїСЂРѕСЃС‚С‹Рµ РѕРіСЂР°РЅРёС‡РµРЅРёСЏ RSI/ATR.

РћР¶РёРґР°РµРјС‹Р№ input features:
{
  "indicators": {"rsi":..., "atr_pct":..., "ema20":..., "ema50":..., "price": ...},
  "rule_score": 0..1,
  "ai_score": 0..1 (optional),
  "market": {"condition": "bullish"|"bearish"|"unknown"}
}
"""
from __future__ import annotations

from typing import Dict, Any


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _mix_scores(rule_score: float, ai_score: float | None, rule_w: float, ai_w: float) -> float:
    if ai_score is None:
        return _clamp01(rule_score)
    total = rule_w + ai_w
    if total <= 0.0:
        return _clamp01(rule_score)
    return _clamp01((rule_score * rule_w + ai_score * ai_w) / total)


def decide(features: Dict[str, Any], cfg) -> Dict[str, Any]:
    ind = (features or {}).get("indicators") or {}
    rule_score = float((features or {}).get("rule_score") or 0.0)
    ai_score = features.get("ai_score") if isinstance(features, dict) else None
    market_cond = ((features or {}).get("market") or {}).get("condition") or "unknown"

    # 1) AI gate (РµСЃР»Рё РІРєР»СЋС‡С‘РЅ)
    if cfg.ENFORCE_AI_GATE:
        # РµСЃР»Рё ai_score РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚ вЂ” РёСЃРїРѕР»СЊР·СѓРµРј failover-РїРѕСЂРѕРі
        _ai = float(ai_score if ai_score is not None else cfg.AI_FAILOVER_SCORE)
        if _ai < float(cfg.AI_MIN_TO_TRADE):
            return {"action": "hold", "reason": f"ai_gate({_ai:.2f}<{cfg.AI_MIN_TO_TRADE:.2f})", "score": _ai}

    # 2) РЎРјРµС€РёРІР°РµРј rule/ai (РІРµСЃ РёР· РЅР°СЃС‚СЂРѕРµРє РёР»Рё РґРµС„РѕР»С‚)
    rule_w = getattr(cfg, "RULE_WEIGHT", 0.6)
    ai_w = getattr(cfg, "AI_WEIGHT", 0.4)
    mixed = _mix_scores(rule_score, ai_score, rule_w, ai_w)

    # 3) РџСЂРѕСЃС‚С‹Рµ risk-С„РёР»СЊС‚СЂС‹ РїРѕ РёРЅРґРёРєР°С‚РѕСЂР°Рј
    rsi = float(ind.get("rsi") or 50.0)
    atr_pct = float(ind.get("atr_pct") or 0.0)
    ema20 = float(ind.get("ema20") or 0.0)
    ema50 = float(ind.get("ema50") or 0.0)

    # RSI Р·Р°С‰РёС‚Р° РѕС‚ РїРµСЂРµРєСѓРїР»РµРЅРЅРѕСЃС‚Рё/РїРµСЂРµРїСЂРѕРґР°РЅРЅРѕСЃС‚Рё
    if rsi >= float(getattr(cfg, "RSI_OVERBOUGHT", 70)):
        return {"action": "hold", "reason": f"rsi_overbought({rsi:.1f})", "score": mixed}

    # Р’РѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ СЃР»РёС€РєРѕРј РІС‹СЃРѕРєР°СЏ?
    vol_th = float(getattr(cfg, "VOLATILITY_THRESHOLD", 5.0))
    if atr_pct > vol_th:
        return {"action": "hold", "reason": f"atr_pct_high({atr_pct:.2f}>{vol_th:.2f})", "score": mixed}

    # 4) РџРѕСЂРѕРі РЅР° РїРѕРєСѓРїРєСѓ
    buy_thr = float(getattr(cfg, "MIN_SCORE_TO_BUY", 0.65))
    if mixed >= buy_thr and ema20 >= ema50 and market_cond != "bearish":
        return {"action": "buy", "reason": f"score_ok({mixed:.2f})", "score": mixed}

    # Р’ РїСЂРѕС‚РёРІРЅРѕРј СЃР»СѓС‡Р°Рµ Р»РёР±Рѕ РїСЂРѕРґР°С‘Рј, РµСЃР»Рё С‚СЂРµРЅРґ РІРЅРёР· (РґР»СЏ СѓРїСЂРѕС‰РµРЅРёСЏ вЂ” СЃРёРіРЅР°Р» РЅР° С„РёРєСЃР°С†РёСЋ)
    if ema20 < ema50 and market_cond == "bearish":
        return {"action": "sell", "reason": "downtrend", "score": mixed}

    return {"action": "hold", "reason": "score_low", "score": mixed}


