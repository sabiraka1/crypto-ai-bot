# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.app.adapters.telegram import handle_update as telegram_handle_update
from crypto_ai_bot.utils.time import monotonic_ms, now_ms
from crypto_ai_bot.utils import metrics as m

logger = logging.getLogger(__name__)
app = FastAPI()

_container = None
_orchestrator = None

@app.on_event("startup")
async def _startup() -> None:
    global _container, _orchestrator
    _container = build_container()
    _orchestrator = _container.orchestrator
    await _orchestrator.start()
    logger.info("server_started")

@app.on_event("shutdown")
async def _shutdown() -> None:
    try:
        if _orchestrator:
            await _orchestrator.stop()
    finally:
        logger.info("server_stopped")

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"ok": True, "ts": now_ms()}

@app.get("/health/extended")
async def health_extended() -> Dict[str, Any]:
    c = _container
    ok = True
    checks: Dict[str, Any] = {}

    # broker latency
    t0 = monotonic_ms()
    try:
        sym = (getattr(c.settings, "SYMBOLS", None) or [getattr(c.settings, "SYMBOL", "BTC/USDT")])[0]
        _ = await c.broker.fetch_ticker(sym)
        checks["exchange_latency_ms"] = monotonic_ms() - t0
        checks["broker_ok"] = True
    except Exception as e:
        checks["broker_ok"] = False
        checks["broker_error"] = repr(e)
        ok = False

    # db ok (kv heartbeat)
    try:
        hb = getattr(c.repos.kv, "get", lambda *_: None)("orchestrator_heartbeat_ms")
        checks["heartbeat_ms"] = hb
        checks["db_ok"] = True
    except Exception as e:
        checks["db_ok"] = False
        checks["db_error"] = repr(e)
        ok = False

    # positions / exits
    try:
        pos_count = 0
        get_all = getattr(c.repos.positions, "get_all", None)
        if callable(get_all):
            pos = await get_all() if asyncio.iscoroutinefunction(get_all) else get_all()
            pos_count = len(pos) if pos is not None else 0
        checks["positions_open"] = pos_count
    except Exception:
        checks["positions_open"] = "n/a"

    try:
        exits_count = 0
        count_active = getattr(c.repos.exits, "count_active", None)
        if callable(count_active):
            exits_count = await count_active() if asyncio.iscoroutinefunction(count_active) else count_active()
        checks["exits_active"] = exits_count
    except Exception:
        checks["exits_active"] = "n/a"

    return {"ok": ok, "ts": now_ms(), "checks": checks}

# ------------------------------ telegram -------------------------------------

def _check_secret(container, request: Request, payload: Dict[str, Any]) -> bool:
    configured = getattr(container.settings, "TELEGRAM_BOT_SECRET", None)
    if not configured:
        return True
    qsec = request.query_params.get("secret")
    hsec = request.headers.get("X-Telegram-Secret")
    psec = payload.get("secret")
    return configured in (qsec, hsec, psec)

@app.get("/telegram")
async def telegram_get(request: Request) -> Response:
    return JSONResponse({"ok": True, "msg": "POST update to /telegram or /telegram/webhook"})

@app.post("/telegram")
async def telegram_post(request: Request) -> Response:
    c = _container
    body = await request.json()
    if not _check_secret(c, request, body):
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    await telegram_handle_update(c, body)
    return JSONResponse({"ok": True})

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> Response:
    c = _container
    body = await request.json()
    if not _check_secret(c, request, body):
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    await telegram_handle_update(c, body)
    return JSONResponse({"ok": True})

# -------------------------------- metrics ------------------------------------

@app.get("/metrics")
def metrics() -> Response:
    # безопасный экспорт; если prometheus_client не установлен — вернём stub
    try:
        body_iter = m.prometheus_app.__call__  # type: ignore[attr-defined]
    except Exception:
        # простой текст — без клиентской библиотеки
        return PlainTextResponse("# no prometheus_client installed\n", status_code=200)
    # Адаптация WSGI → простая прокладка
    chunks: list[bytes] = []
    status_line = ""
    headers: list[tuple[str, str]] = []

    def start_response(s: str, h: list[tuple[str, str]]):
        nonlocal status_line, headers
        status_line = s
        headers = h

    for part in m.prometheus_app({}, start_response):  # type: ignore
        chunks.append(part)

    status_code = int(status_line.split()[0] or "200") if status_line else 200
    # FastAPI сам выставит Content-Type
    return Response(content=b"".join(chunks), status_code=status_code, media_type="text/plain")
