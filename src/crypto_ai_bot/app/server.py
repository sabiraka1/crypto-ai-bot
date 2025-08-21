from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)
app = FastAPI(title="crypto-ai-bot")


@app.on_event("startup")
async def _startup() -> None:
    c = build_container()
    app.state.container = c
    app.state.orchestrator = Orchestrator(c)
    # запуск оркестратора можно отложить; сейчас включим, чтобы клей был полный
    try:
        await app.state.orchestrator.start()
    except Exception:
        logger.exception("orchestrator_start_failed")


@app.on_event("shutdown")
async def _shutdown() -> None:
    try:
        if getattr(app.state, "orchestrator", None):
            await app.state.orchestrator.stop()
    except Exception:
        logger.exception("orchestrator_stop_failed")


@app.get("/health")
async def health() -> Dict[str, Any]:
    c = app.state.container
    ok_db = False
    try:
        if getattr(c, "con", None):
            c.con.execute("SELECT 1")
            ok_db = True
    except Exception:
        ok_db = False

    ok_bus = True
    try:
        _ = c.bus.qsize()
    except Exception:
        ok_bus = False

    ok_broker = hasattr(c.broker, "fetch_ticker")

    overall = ok_db and ok_bus and ok_broker
    return {
        "ok": overall,
        "db": ok_db,
        "bus": ok_bus,
        "broker": ok_broker,
        "mode": c.settings.MODE,
        "symbol": c.settings.SYMBOL,
    }


@app.get("/status")
async def status() -> Dict[str, Any]:
    c = app.state.container
    orch = getattr(app.state, "orchestrator", None)
    running = bool(orch and orch._running)
    tasks = len(orch.tasks) if orch else 0
    return {
        "mode": c.settings.MODE,
        "exchange": c.settings.EXCHANGE,
        "symbol": c.settings.SYMBOL,
        "bus_qsize": c.bus.qsize() if hasattr(c.bus, "qsize") else None,
        "orchestrator_running": running,
        "orchestrator_tasks": tasks,
    }


@app.get("/metrics")
async def metrics() -> Response:
    """
    Простейшая отдача метрик в формате Prometheus (минимум).
    При желании позже заменим на prometheus_client.
    """
    lines = [
        "# HELP app_up 1 if app is up",
        "# TYPE app_up gauge",
        "app_up 1",
    ]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.post("/telegram/webhook")
async def telegram_webhook(req: Request) -> JSONResponse:
    c = app.state.container
    try:
        payload = await req.json()
    except Exception:
        payload = {}

    try:
        from crypto_ai_bot.app.adapters.telegram import handle_update
        await handle_update(c, payload)
        return JSONResponse({"ok": True})
    except Exception:
        logger.exception("telegram_webhook_failed")
        return JSONResponse({"ok": False}, status_code=500)
