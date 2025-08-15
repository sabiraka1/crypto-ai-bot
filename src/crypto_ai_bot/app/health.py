# src/crypto_ai_bot/app/health.py
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.signals.aggregator import aggregate_features
from crypto_ai_bot.context.snapshot import ContextSnapshot

logger = logging.getLogger(__name__)

# --- Р±Р°Р·РѕРІС‹Рµ health С‡РµРєРµСЂС‹ ---------------------------------------------------
router = APIRouter()

@router.get("/health/live")
def live() -> Dict[str, str]:
    return {"status": "ok"}

@router.get("/health/ready")
def ready() -> Dict[str, str]:
    return {"status": "ready"}


# --- РїРѕР»РЅРѕС†РµРЅРЅС‹Р№ /status -----------------------------------------------------
def build_status_router(bot, deps) -> APIRouter:
    """
    /status С‚РµРїРµСЂСЊ СЃРѕС‡РµС‚Р°РµС‚:
      1) С‚РµРєСѓС‰РµРµ СЃРѕСЃС‚РѕСЏРЅРёРµ РёР· StateManager (РєР°Рє Р±С‹Р»Рѕ Сѓ С‚РµР±СЏ)
      2) РєСЂР°С‚РєСѓСЋ СЂС‹РЅРѕС‡РЅСѓСЋ СЃРІРѕРґРєСѓ РёР· Р°РіСЂРµРіР°С‚РѕСЂР° (rule-score, ATR%, СЂРµР¶РёРј)
    РќРёС‡РµРіРѕ РЅРµ Р»РѕРјР°РµРј: РїСЂРµР¶РЅРёРµ РїРѕР»СЏ РѕСЃС‚Р°СЋС‚СЃСЏ.
    """
    r = APIRouter()

    @r.get("/status")
    def status():
        cfg: Settings = deps.settings

        # 1) СЃРѕСЃС‚РѕСЏРЅРёРµ (РєР°Рє Сѓ С‚РµР±СЏ СЂР°РЅСЊС€Рµ)
        st = getattr(deps.state, "state", {}) or {}
        base = {
            "running": True,
            "bot_running": bool(getattr(bot, "_running", True)),
            "symbol": getattr(cfg, "SYMBOL", "BTC/USDT"),
            "timeframe": getattr(cfg, "TIMEFRAME", "15m"),
            "safe_mode": bool(getattr(cfg, "SAFE_MODE", True)),
            "in_position": bool(st.get("in_position", False)),
            "opening": bool(st.get("opening", False)),
            "cooldown": bool(st.get("cooldown", False)),
            "equity": st.get("equity", 0),
            "daily_drawdown": st.get("daily_drawdown", 0),
            "last_manage_check": st.get("last_manage_check"),
        }

        # 2) СЂС‹РЅРѕС‡РЅР°СЏ СЃРІРѕРґРєР° (Р±РµР·РѕРїР°СЃРЅРѕ: РµСЃР»Рё С‡С‚Рѕ-С‚Рѕ РїРѕР№РґС‘С‚ РЅРµ С‚Р°Рє вЂ” РїСЂРѕСЃС‚Рѕ РІРµСЂРЅС‘Рј base)
        try:
            snap = ContextSnapshot.neutral()  # СЃСЋРґР° РїРѕР·Р¶Рµ РїРѕРґСЃС‚Р°РІРёРј СЂРµР°Р»СЊРЅС‹Р№ РєРѕРЅС‚РµРєСЃС‚
            feat = aggregate_features(cfg, deps.exchange, snap)

            if "error" not in feat:
                ind = feat.get("indicators", {})
                market = {
                    "condition": feat.get("context", {}).get("market_condition"),
                    "atr_pct": ind.get("atr_pct"),
                }
                scores = {
                    "rule": feat.get("rule_score"),
                    "ai": feat.get("ai_score"),
                    "total_hint": feat.get("rule_score"),  # РїРѕРєР° rule вЂ” РѕСЃРЅРѕРІРЅРѕР№
                }
                dataq = {
                    "primary_candles": feat.get("data_quality", {}).get("primary_candles"),
                    "timeframes_ok": feat.get("data_quality", {}).get("timeframes_ok"),
                    "timeframes_failed": feat.get("data_quality", {}).get("timeframes_failed"),
                    "indicators_count": feat.get("data_quality", {}).get("indicators_count"),
                }

                base.update({
                    "scores": scores,
                    "market": market,
                    "data": dataq,
                    "timestamp": feat.get("timestamp"),
                })
            else:
                base.update({"aggregation_error": feat.get("error")})
        except Exception as e:
            logger.error(f"/status aggregation failed: {e}", exc_info=True)

        return JSONResponse(base)

    # --- /metrics: Prometheus РµСЃР»Рё СѓСЃС‚Р°РЅРѕРІР»РµРЅ, РёРЅР°С‡Рµ РѕСЃС‚Р°РІР»СЏРµРј РєР°Рє РµСЃС‚СЊ -------
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest  # type: ignore

        @r.get("/metrics", response_class=PlainTextResponse)
        def metrics_prom():
            data = generate_latest(REGISTRY)
            return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    except Exception:
        # РµСЃР»Рё prometheus_client РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ вЂ” СЌС‚РѕС‚ СЂРѕСѓС‚РµСЂ РЅРµ РґРѕР±Р°РІР»СЏРµРј,
        # С‚РІРѕР№ JSON-С„РѕР»Р±СЌРє РѕСЃС‚Р°РЅРµС‚СЃСЏ РґРѕСЃС‚СѓРїРЅС‹Рј РІ РґСЂСѓРіРѕРј РјРµСЃС‚Рµ (РєР°Рє СЃРµР№С‡Р°СЃ)
        pass

    return r





