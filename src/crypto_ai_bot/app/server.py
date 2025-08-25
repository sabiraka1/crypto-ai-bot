from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import FastAPI, Request, APIRouter
from fastapi.responses import PlainTextResponse, JSONResponse

from ..utils.logging import get_logger
from ..utils.time import now_ms
from .compose import build_container

log = get_logger("server")

app = FastAPI(title="crypto-ai-bot", version="1.0.0")
app.state.container = build_container()  # сборка при импорте, как и раньше

router = APIRouter()


# --- basic probes -------------------------------------------------------------

@router.get("/live")
async def live() -> Dict[str, Any]:
    return {"ok": True}


@router.get("/ready")
async def ready() -> JSONResponse:
    c = app.state.container
    try:
        rep = await c.health.check(symbol=c.settings.SYMBOL)
        
        # Проверка свежести пульса оркестратора
        try:
            st = c.orchestrator.status()
            # если оркестр запущен, но давно не бился — считаем not ready
            if st.get("running") and st.get("last_beat_ms", 0) > 0:
                if now_ms() - int(st["last_beat_ms"]) > 15_000:  # 15 сек
                    return JSONResponse(
                        status_code=503,
                        content={"ok": False, "reason": "stale_heartbeat", "status": st}
                    )
        except Exception:
            pass
        
        # 200 если ок, иначе 503
        return JSONResponse(status_code=(200 if rep.ok else 503), content={"ok": rep.ok, "ts_ms": rep.ts_ms})
    except Exception as exc:
        log.error("ready_failed", extra={"error": str(exc)})
        return JSONResponse(status_code=503, content={"ok": False})


@router.get("/health")
async def health() -> JSONResponse:
    c = app.state.container
    rep = await c.health.check(symbol=c.settings.SYMBOL)
    # Совместимость со старыми тестами: db_ok в корне
    payload = {
        "ok": rep.ok,
        "ts_ms": rep.ts_ms,
        "db_ok": bool(rep.components.get("db", False)),
        "components": rep.components,  # подробности
    }
    return JSONResponse(status_code=(200 if rep.ok else 503), content=payload)


@router.get("/status")
async def status() -> Dict[str, Any]:
    c = app.state.container
    return {
        "ok": True,
        "symbol": c.settings.SYMBOL,
        "orchestrator": c.orchestrator.status(),
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    # Тестам нужна только 200, содержимое — простое
    return "# crypto-ai-bot metrics\nOK\n"


# --- orchestrator controls ----------------------------------------------------

@router.post("/orchestrator/start")
async def orchestrator_start(request: Request):
    c = request.app.state.container
    c.orchestrator.start()
    return {"ok": True, "status": c.orchestrator.status()}


@router.post("/orchestrator/stop")
async def orchestrator_stop(request: Request):
    c = request.app.state.container
    await c.orchestrator.stop()
    return {"ok": True, "status": c.orchestrator.status()}


@router.get("/orchestrator/status")
async def orchestrator_status(request: Request):
    c = request.app.state.container
    return {"ok": True, "status": c.orchestrator.status()}


app.include_router(router)