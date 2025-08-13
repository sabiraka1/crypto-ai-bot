# src/crypto_ai_bot/app/health.py
from __future__ import annotations

from fastapi import APIRouter
from crypto_ai_bot.trading.bot import TradingBot, Deps
from crypto_ai_bot.trading.risk_manager import RiskManager

router = APIRouter(prefix="/health", tags=["health"])

@router.get("/live")
def live() -> dict:
    return {"status": "ok"}

@router.get("/ready")
def ready() -> dict:
    return {"ready": True}

def build_status_router(bot: TradingBot, deps: Deps) -> APIRouter:
    r = APIRouter(tags=["status"])

    @r.get("/status")
    def status() -> dict:
        st = deps.state.state
        return {
            "running": True,                # сам факт, что сервер отвечает
            "bot_running": getattr(bot, "_running", False),
            "symbol": deps.settings.SYMBOL,
            "timeframe": deps.settings.TIMEFRAME,
            "safe_mode": deps.settings.SAFE_MODE,
            "in_position": bool(st.get("in_position")),
            "opening": bool(st.get("opening")),
            "cooldown": deps.state.in_cooldown(),
            "equity": st.get("equity"),
            "daily_drawdown": deps.state.get_daily_drawdown(),
            "last_manage_check": st.get("last_manage_check"),
        }

    @r.get("/metrics")
    def metrics() -> dict:
        rm = deps.risk if isinstance(deps.risk, RiskManager) else None
        risk_info = rm.get_status_summary() if rm else {}
        return {
            "risk": risk_info,
            "positions_open": deps.state.get_open_positions_count(),
        }

    @r.post("/bot/start")
    def bot_start() -> dict:
        if getattr(bot, "_running", False):
            return {"ok": True, "message": "already running"}
        bot.start()
        return {"ok": True, "message": "started"}

    @r.post("/bot/stop")
    def bot_stop() -> dict:
        if not getattr(bot, "_running", False):
            return {"ok": True, "message": "already stopped"}
        bot.stop()
        return {"ok": True, "message": "stopped"}

    return r
