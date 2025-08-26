from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import PlainTextResponse, JSONResponse

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.metrics import render_prometheus
from crypto_ai_bot.core.analytics.metrics import render_metrics_json
from .compose import build_container

log = get_logger("server")


# ------------------ Жизненный цикл ------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    app.state.container = build_container()
    c = app.state.container

    try:
        orch = getattr(c, "orchestrator", None)
        if orch:
            orch.start()
        else:
            orchestrators: Dict[str, Any] = getattr(c, "orchestrators", {}) or {}
            for o in orchestrators.values():
                o.start()
        yield
    finally:
        try:
            orch = getattr(c, "orchestrator", None)
            if orch:
                await orch.stop()
            else:
                orchestrators: Dict[str, Any] = getattr(c, "orchestrators", {}) or {}
                for o in orchestrators.values():
                    await o.stop()
        except Exception as exc:
            log.warning("shutdown_failed", extra={"error": str(exc)})
        app.state.container = None


app = FastAPI(title="crypto-ai-bot", version="1.0.0", lifespan=lifespan)


# ------------------ Базовые проверки ------------------

@app.get("/live")
async def live() -> Dict[str, Any]:
    return {"ok": True}


@app.get("/ready")
async def ready() -> JSONResponse:
    c = app.state.container
    if not c:
        return JSONResponse(status_code=503, content={"ok": False, "reason": "no_container"})
    try:
        rep = await c.health.check(symbol=c.settings.SYMBOL)

        # Проверка heartbeat оркестратора
        try:
            st = c.orchestrator.status()
            if st.get("running") and st.get("last_beat_ms", 0) > 0:
                if now_ms() - int(st["last_beat_ms"]) > 15_000:
                    return JSONResponse(
                        status_code=503,
                        content={"ok": False, "reason": "stale_heartbeat", "status": st}
                    )
        except Exception:
            pass

        return JSONResponse(status_code=(200 if rep.ok else 503),
                            content={"ok": rep.ok, "ts_ms": rep.ts_ms})
    except Exception as exc:
        log.error("ready_failed", extra={"error": str(exc)})
        return JSONResponse(status_code=503, content={"ok": False})


@app.get("/health")
async def health() -> JSONResponse:
    c = app.state.container
    if not c:
        return JSONResponse(status_code=503, content={"ok": False, "reason": "no_container"})
    rep = await c.health.check(symbol=c.settings.SYMBOL)
    payload = {
        "ok": rep.ok,
        "ts_ms": rep.ts_ms,
        "db_ok": bool(rep.components.get("db", False)),
        "components": rep.components,
    }
    return JSONResponse(status_code=(200 if rep.ok else 503), content=payload)


@app.get("/status")
async def status_endpoint() -> Dict[str, Any]:
    c = app.state.container
    if not c:
        return {"running": False}
    orch = getattr(c, "orchestrator", None)
    if orch:
        return {"running": True, "orchestrators": {"default": orch.status()}}
    orchestrators: Dict[str, Any] = getattr(c, "orchestrators", {}) or {}
    return {"running": bool(orchestrators),
            "orchestrators": {k: v.status() for k, v in orchestrators.items()}}


# ------------------ Метрики ------------------

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    try:
        return render_prometheus()
    except Exception:
        data = render_metrics_json()
        return "# metrics fallback\n" + str(data) + "\n"


# ------------------ Управление оркестратором ------------------

@app.post("/orchestrator/start")
async def orchestrator_start(request: Request):
    c = request.app.state.container
    c.orchestrator.start()
    return {"ok": True, "status": c.orchestrator.status()}


@app.post("/orchestrator/stop")
async def orchestrator_stop(request: Request):
    c = request.app.state.container
    await c.orchestrator.stop()
    return {"ok": True, "status": c.orchestrator.status()}


@app.get("/orchestrator/status")
async def orchestrator_status(request: Request):
    c = request.app.state.container
    return {"ok": True, "status": c.orchestrator.status()}
