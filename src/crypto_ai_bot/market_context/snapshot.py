# src/crypto_ai_bot/market_context/snapshot.py
from __future__ import annotations

import time
from typing import Any, Dict

from crypto_ai_bot.utils.cache import GLOBAL_CACHE
from crypto_ai_bot.market_context.indicators.btc_dominance import fetch_btc_dominance
from crypto_ai_bot.market_context.indicators.fear_greed import fetch_fear_greed
from crypto_ai_bot.market_context.indicators.dxy_index import fetch_dxy
from crypto_ai_bot.market_context.regime_detector import detect_regime


def _weight_or_zero(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _composite(ind: Dict[str, float], w: Dict[str, float], decision_weight: float) -> float:
    """
    Простой взвешенный скор:
        score = decision_weight * ( w_fng * fng + w_dxy * (1 - dxy) + w_dom * dom ) / (w_fng + w_dxy + w_dom, если >0)
    DXY инвертируем (сильный доллар часто = risk-off).
    """
    wf = _weight_or_zero(w.get("fng", w.get("fear_greed", 0.0)))
    wd = _weight_or_zero(w.get("dxy", 0.0))
    wb = _weight_or_zero(w.get("btc_dom", w.get("btc_dominance", 0.0)))

    denom = wf + wd + wb
    if denom <= 0.0:
        return 0.0

    s = wf * float(ind.get("fear_greed", 0.0)) + wd * (1.0 - float(ind.get("dxy", 0.0))) + wb * float(ind.get("btc_dominance", 0.0))
    return max(0.0, min(1.0, float(decision_weight) * (s / denom)))


def build_snapshot(cfg: Any, http: Any, breaker: Any) -> Dict[str, Any]:
    """
    Основной entrypoint. Возвращает MarketContext (dict), кэшируется на CONTEXT_CACHE_TTL_SEC.
    Источники берём из Settings:
      - CONTEXT_BTC_DOMINANCE_URL
      - CONTEXT_FEAR_GREED_URL
      - CONTEXT_DXY_URL
      - CONTEXT_*_WEIGHT + CONTEXT_DECISION_WEIGHT или PRESET
    """
    if not getattr(cfg, "CONTEXT_ENABLE", True):
        return {"ts_ms": int(time.time() * 1000), "indicators": {}, "weights": {}, "composite": 0.0, "regime": "neutral", "sources": {}}

    ttl = float(getattr(cfg, "CONTEXT_CACHE_TTL_SEC", 300) or 300)
    cache_key = "market_context:v2"
    cached = GLOBAL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    btc_url = str(getattr(cfg, "CONTEXT_BTC_DOMINANCE_URL", "") or "")
    fng_url = str(getattr(cfg, "CONTEXT_FEAR_GREED_URL", "") or "")
    dxy_url = str(getattr(cfg, "CONTEXT_DXY_URL", "") or "")

    dom = fetch_btc_dominance(http, breaker, btc_url, timeout=float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0)))
    fng = fetch_fear_greed(http, breaker, fng_url, timeout=float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0)))
    dxy = fetch_dxy(http, breaker, dxy_url, timeout=float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0)))

    indicators = {}
    if dom is not None: indicators["btc_dominance"] = float(dom)
    if fng is not None: indicators["fear_greed"] = float(fng)
    if dxy is not None: indicators["dxy"] = float(dxy)

    weights = {
        "btc_dom": float(getattr(cfg, "CTX_BTC_DOM_WEIGHT", 0.0) or 0.0),
        "fng": float(getattr(cfg, "CTX_FNG_WEIGHT", 0.0) or 0.0),
        "dxy": float(getattr(cfg, "CTX_DXY_WEIGHT", 0.0) or 0.0),
    }
    decision_weight = float(getattr(cfg, "CONTEXT_DECISION_WEIGHT", 0.0) or 0.0)

    comp = _composite(indicators, weights, decision_weight)
    regime = detect_regime(indicators)

    out = {
        "ts_ms": int(time.time() * 1000),
        "sources": {"btc_dominance": bool(btc_url), "fear_greed": bool(fng_url), "dxy": bool(dxy_url)},
        "indicators": indicators,
        "weights": {"decision": decision_weight, **weights},
        "composite": comp,
        "regime": regime,
    }
    GLOBAL_CACHE.set(cache_key, out, ttl_sec=ttl)
    return out
