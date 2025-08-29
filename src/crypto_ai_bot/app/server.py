# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from ..utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec
from ..utils.metrics import render_prometheus, render_metrics_json
from ..utils.time import now_ms
from ..utils.exceptions import (
    TradingError,
    ValidationError,
    BrokerError,
    TransientError,
    IdempotencyError,
    CircuitOpenError,
)
from .compose import build_container

_log = get_logger("server")

app = FastAPI(title="crypto-ai-bot", version="1.0.0")
_container = None

router = APIRouter()
security = HTTPBearer(auto_error=False)


async def _auth(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> None:
    if not _container:
        raise HTTPException(status_code=503, detail="Service Unavailable")
    token_required = _container.settings.API_TOKEN
    if not token_required:
        return
    if not credentials or credentials.credentials != token_required:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.on_event("startup")
async def _startup() -> None:
    global _container
    _container = build_container()
    
    # авто-старт оркестратора
    autostart = bool(_container.settings.TRADER_AUTOSTART) or _container.settings.MODE == "live"
    if autostart:
        loop = asyncio.get_running_loop()
        loop.call_soon(_container.orchestrator.start)
        _log.info("orchestrator_autostart_enabled", extra={"mode": _container.settings.MODE})


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _container and _container.orchestrator:
        try:
            st = _container.orchestrator.status()
            if st.get("running"):
                await _container.orchestrator.stop()
                _log.info("orchestrator_stopped_on_shutdown")
        except Exception as exc:
            _log.error("shutdown_failed", extra={"error": str(exc)})


@app.exception_handler(TradingError)
async def trading_error_handler(request: Request, exc: TradingError):
    if isinstance(exc, ValidationError):
        code = 400
    elif isinstance(exc, IdempotencyError):
        code = 409
    elif isinstance(exc, BrokerError):
        code = 502
    elif isinstance(exc, (TransientError, CircuitOpenError)):
        code = 503
    else:
        code = 500
    return JSONResponse(status_code=code, content={"ok": False, "error": exc.__class__.__name__, "detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    _log.error("unhandled_error", extra={"error": str(exc)})
    return JSONResponse(status_code=500, content={"ok": False, "error": "InternalServerError"})


@router.get("/")
async def root() -> Dict[str, Any]:
    return {"name": "crypto-ai-bot", "version": "1.0.0"}


@router.get("/live")
async def live() -> Dict[str, Any]:
    return {"ok": True, "ts_ms": now_ms()}


@router.get("/ready")
async def ready() -> JSONResponse:
    if not _container:
        return JSONResponse(status_code=503, content={"ok": False, "error": "container_not_ready"})
    try:
        rep = await _container.health.check(symbol=_container.settings.SYMBOL)
        return JSONResponse(
            status_code=(200 if rep.ok else 503),
            content={"ok": rep.ok, "components": rep.components, "ts_ms": rep.ts_ms},
        )
    except Exception as exc:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})


@router.get("/health")
async def health() -> JSONResponse:
    if not _container:
        return JSONResponse(status_code=503, content={"ok": False, "error": "container_not_ready"})
    rep = await _container.health.check(symbol=_container.settings.SYMBOL)
    return JSONResponse(
        status_code=(200 if rep.ok else 503),
        content={"ok": rep.ok, "ts_ms": rep.ts_ms, "components": rep.components},
    )


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    try:
        return render_prometheus()
    except Exception:
        data = render_metrics_json()
        return "#metrics_fallback\n" + str(data) + "\n"


@router.get("/orchestrator/status")
async def orchestrator_status(request: Request, _: Any = Depends(_auth)) -> Dict[str, Any]:
    return {"ok": True, "status": _container.orchestrator.status()}


@router.post("/orchestrator/start")
async def orchestrator_start(request: Request, _: Any = Depends(_auth)) -> Dict[str, Any]:
    if _container.orchestrator.status().get("running"):
        return {"ok": True, "message": "already_running"}
    _container.orchestrator.start()
    return {"ok": True, "message": "started"}


@router.post("/orchestrator/stop")
async def orchestrator_stop(request: Request, _: Any = Depends(_auth)) -> Dict[str, Any]:
    await _container.orchestrator.stop()
    return {"ok": True, "message": "stopped"}


@router.get("/positions")
async def get_positions(request: Request, _: Any = Depends(_auth)) -> Dict[str, Any]:
    pos = _container.storage.positions.get_position(_container.settings.SYMBOL)
    t = await _container.broker.fetch_ticker(_container.settings.SYMBOL)
    unreal = (t.last - (pos.avg_entry_price or dec("0"))) * (pos.base_qty or dec("0"))
    return {
        "symbol": _container.settings.SYMBOL,
        "base_qty": str(pos.base_qty or dec("0")),
        "avg_price": str(pos.avg_entry_price or dec("0")),
        "current_price": str(t.last),
        "unrealized_pnl": str(unreal),
    }


@router.get("/trades")
async def get_trades(request: Request, limit: int = 100, _: Any = Depends(_auth)) -> Dict[str, Any]:
    rows = _container.storage.trades.list_recent(_container.settings.SYMBOL, limit)
    return {"trades": rows, "total": len(rows)}


@router.get("/performance")
async def performance(request: Request, _: Any = Depends(_auth)) -> Dict[str, Any]:
    """PNL за сегодня: sells - buys по данным из БД (реализованный)."""
    rows = _container.storage.trades.list_today(_container.settings.SYMBOL)
    buys = sum(dec(r["cost"]) for r in rows if str(r["side"]).lower() == "buy")
    sells = sum(dec(r["cost"]) for r in rows if str(r["side"]).lower() == "sell")
    realized = sells - buys
    return {
        "symbol": _container.settings.SYMBOL,
        "total_trades": len(rows),
        "buys_quote": str(buys),
        "sells_quote": str(sells),
        "realized_quote": str(realized),
    }


app.include_router(router)
