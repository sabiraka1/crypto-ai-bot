from __future__ import annotations

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse, JSONResponse

from ..core.settings import Settings
from .compose import build_container

# метрики: стараемся отдать Prometheus-текст, иначе JSON-фолбэк
try:
    from ..core.analytics.metrics import report_dict as metrics_report_dict
except Exception:  # на случай если модуль недоступен
    metrics_report_dict = None

from ..utils.metrics import prometheus_text, snapshot

app = FastAPI(title="crypto-ai-bot")
app.state.container = build_container()


@app.get("/health")
async def health() -> dict:
    c = app.state.container
    rep = await c.health.check(symbol=c.settings.SYMBOL)
    return {
        "ok": rep.ok,
        "components": rep.components,
        "ts_ms": rep.ts_ms,
    }


@app.get("/ready")
async def ready() -> dict:
    # простая готовность: контейнер собран и брокер есть
    c = app.state.container
    return {"ok": c is not None and c.broker is not None}


@app.get("/metrics")
async def metrics() -> Response:
    # Пытаемся выдать Prom-текст (если метрики были инкрементированы)
    text = prometheus_text()
    if text.strip():
        return PlainTextResponse(text, media_type="text/plain; version=0.0.4")
    # Иначе — JSON фолбэк (как раньше)
    if metrics_report_dict:
        try:
            return JSONResponse(metrics_report_dict())
        except Exception:
            pass
    return JSONResponse(snapshot())


# --- новый агрегатор статуса системы ---
@app.get("/status")
async def status() -> dict:
    c = app.state.container
    # базовые
    s = c.settings
    # bus
    bus_q = c.bus.qsize()
    # risk
    rc = c.risk
    cfg = rc._cfg  # dataclass RiskConfig
    # orchestrator
    orch = c.orchestrator.status()

    return {
        "ok": True,
        "mode": s.MODE,
        "exchange": s.EXCHANGE,
        "symbol": s.SYMBOL,
        "risk": {
            "cooldown_sec": cfg.cooldown_sec,
            "max_spread_pct": cfg.max_spread_pct,
            "max_position_base": str(cfg.max_position_base) if cfg.max_position_base is not None else None,
            "max_orders_per_hour": cfg.max_orders_per_hour,
            "daily_loss_limit_quote": str(cfg.daily_loss_limit_quote) if cfg.daily_loss_limit_quote is not None else None,
        },
        "bus": {"qsize": bus_q},
        "orchestrator": orch,
    }


# --- ручки оркестратора (если уже были — оставляем без изменений) ---
@app.post("/orchestrator/start")
async def orchestrator_start() -> dict:
    c = app.state.container
    c.orchestrator.start()
    return {"ok": True, "status": c.orchestrator.status()}


@app.post("/orchestrator/stop")
async def orchestrator_stop() -> dict:
    c = app.state.container
    await c.orchestrator.stop()
    return {"ok": True, "status": c.orchestrator.status()}


@app.get("/orchestrator/status")
async def orchestrator_status() -> dict:
    c = app.state.container
    return {"ok": True, "status": c.orchestrator.status()}
