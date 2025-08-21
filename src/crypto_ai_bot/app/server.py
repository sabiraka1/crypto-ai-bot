## `server.py`
from __future__ import annotations
import json
from typing import Any, Dict
from fastapi import FastAPI, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from .compose import lifespan, Container
from ..core.analytics.metrics import report_dict
try:  # prometheus is optional
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST  # type: ignore
except Exception:  # pragma: no cover
    generate_latest = None  # type: ignore
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"  # type: ignore
app = FastAPI(lifespan=lifespan, title="crypto_ai_bot")
@app.get("/live")
async def live():
    return {"ok": True}
@app.get("/ready")
async def ready():
    c: Container = app.state.container
    try:
        c.storage.conn.execute("SELECT 1;")
        ok = True
    except Exception:
        ok = False
    return JSONResponse({"ok": ok}, status_code=(status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE))
@app.get("/health")
async def health():
    c: Container = app.state.container
    rep = await c.health.check(symbol=c.settings.SYMBOL)
    code = status.HTTP_200_OK if rep.ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(rep.as_dict(), status_code=code)
@app.get("/status")
async def status_endpoint():
    c: Container = app.state.container
    return {
        "settings": c.settings.as_dict(),
        "counters": {
            "trades": len(c.storage.trades.list_recent(limit=1_000_000)),
            "audit": len(c.storage.audit.list_recent(limit=1_000)),
        },
    }
@app.get("/metrics")
async def metrics():
    if generate_latest is not None:
        out = generate_latest()  # type: ignore
        return Response(content=out, media_type=CONTENT_TYPE_LATEST)
    c: Container = app.state.container
    return report_dict(c.storage, symbol=c.settings.SYMBOL)
from .adapters.telegram import router as telegram_router  # noqa: E402
app.include_router(telegram_router, prefix="/telegram")