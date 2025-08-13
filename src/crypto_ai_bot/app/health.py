# src/crypto_ai_bot/app/health.py
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from crypto_ai_bot.config.settings import Settings
from crypto_ai_bot.trading.signals.signal_aggregator import aggregate_features
from crypto_ai_bot.context.snapshot import ContextSnapshot

logger = logging.getLogger(__name__)

# --- базовые health чекеры ---------------------------------------------------
router = APIRouter()

@router.get("/health/live")
def live() -> Dict[str, str]:
    return {"status": "ok"}

@router.get("/health/ready")
def ready() -> Dict[str, str]:
    return {"status": "ready"}


# --- полноценный /status -----------------------------------------------------
def build_status_router(bot, deps) -> APIRouter:
    """
    /status теперь сочетает:
      1) текущее состояние из StateManager (как было у тебя)
      2) краткую рыночную сводку из агрегатора (rule-score, ATR%, режим)
    Ничего не ломаем: прежние поля остаются.
    """
    r = APIRouter()

    @r.get("/status")
    def status():
        cfg: Settings = deps.settings

        # 1) состояние (как у тебя раньше)
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

        # 2) рыночная сводка (безопасно: если что-то пойдёт не так — просто вернём base)
        try:
            snap = ContextSnapshot.neutral()  # сюда позже подставим реальный контекст
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
                    "total_hint": feat.get("rule_score"),  # пока rule — основной
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

    # --- /metrics: Prometheus если установлен, иначе оставляем как есть -------
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest  # type: ignore

        @r.get("/metrics", response_class=PlainTextResponse)
        def metrics_prom():
            data = generate_latest(REGISTRY)
            return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    except Exception:
        # если prometheus_client не установлен — этот роутер не добавляем,
        # твой JSON-фолбэк останется доступным в другом месте (как сейчас)
        pass

    return r
