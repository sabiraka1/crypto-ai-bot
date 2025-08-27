from __future__ import annotations

import os
import asyncio
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from crypto_ai_bot.app.compose import build_container

app = FastAPI(title="crypto-ai-bot")

_container = None

@app.on_event("startup")
async def _startup() -> None:
    global _container
    _container = build_container()
    autostart = os.getenv("TRADER_AUTOSTART", "0") in ("1", "true", "yes") or _container.settings.MODE == "live"
    if autostart:
        # стартуем в фоне, не блокируя event loop
        loop = asyncio.get_running_loop()
        loop.call_soon(_container.orchestrator.start)

@app.on_event("shutdown")
async def _shutdown() -> None:
    if _container and _container.orchestrator:
        try:
            await _container.orchestrator.stop()
        except Exception:
            pass

@app.get("/health")
async def health():
    rep = await _container.health.check(symbol=_container.settings.SYMBOL)
    return {"ok": rep.ok, "ts_ms": rep.ts_ms, "components": rep.components}

@app.get("/ready")
async def ready():
    return {"ok": True}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/orchestrator/start")
async def orc_start():
    _container.orchestrator.start()
    return {"ok": True}

@app.post("/orchestrator/stop")
async def orc_stop():
    await _container.orchestrator.stop()
    return {"ok": True}

@app.get("/")
async def root():
    return {"name": "crypto-ai-bot"}
