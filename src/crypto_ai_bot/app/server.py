from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from ..utils.logging import get_logger
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
app.state.container = build_container()

router = APIRouter()
security = HTTPBearer(auto_error=False)


async def _auth(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> None:
    token_required = request.app.state.container.settings.API_TOKEN
    if not token_required:
        return
    if not credentials or credentials.credentials != token_required:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    try:
        c = app.state.container
        st = c.orchestrator.status()
        if st.get("running"):
            await c.orchestrator.stop()
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


@router.get("/live")
async def live() -> Dict[str, Any]:
    return {"ok": True, "ts_ms": now_ms()}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    try:
        c = request.app.state.container
        rep = await c.health.check(symbol=c.settings.SYMBOL)
        return JSONResponse(
            status_code=(200 if rep.ok else 503),
            content={"ok": rep.ok, "components": rep.components, "ts_ms": rep.ts_ms},
        )
    except Exception as exc:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    c = request.app.state.container
    rep = await c.health.check(symbol=c.settings.SYMBOL)
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
    c = request.app.state.container
    return {"ok": True, "status": c.orchestrator.status()}


@router.post("/orchestrator/start")
async def orchestrator_start(request: Request, _: Any = Depends(_auth)) -> Dict[str, Any]:
    c = request.app.state.container
    if c.orchestrator.status().get("running"):
        return {"ok": True, "message": "already_running"}
    c.orchestrator.start()
    return {"ok": True, "message": "started"}


@router.post("/orchestrator/stop")
async def orchestrator_stop(request: Request, _: Any = Depends(_auth)) -> Dict[str, Any]:
    c = request.app.state.container
    await c.orchestrator.stop()
    return {"ok": True, "message": "stopped"}


@router.get("/positions")
async def get_positions(request: Request, _: Any = Depends(_auth)) -> Dict[str, Any]:
    c = request.app.state.container
    pos = c.storage.positions.get_position(c.settings.SYMBOL)
    t = await c.broker.fetch_ticker(c.settings.SYMBOL)
    unreal = (t.last - (pos.avg_entry_price or Decimal("0"))) * (pos.base_qty or Decimal("0"))
    return {
        "symbol": c.settings.SYMBOL,
        "base_qty": str(pos.base_qty or Decimal("0")),
        "avg_price": str(pos.avg_entry_price or Decimal("0")),
        "current_price": str(t.last),
        "unrealized_pnl": str(unreal),
    }


@router.get("/trades")
async def get_trades(request: Request, limit: int = 100, _: Any = Depends(_auth)) -> Dict[str, Any]:
    c = request.app.state.container
    rows = c.storage.trades.list_recent(c.settings.SYMBOL, limit)
    return {"trades": rows, "total": len(rows)}


@router.get("/performance")
async def performance(request: Request, _: Any = Depends(_auth)) -> Dict[str, Any]:
    c = request.app.state.container
    trades = c.storage.trades.list_today(c.settings.SYMBOL)
    realized = sum(Decimal(r["cost"]) if r["side"] == "sell" else Decimal("0") for r in trades)
    return {"total_trades": len(trades), "realized_quote": str(realized)}


app.include_router(router)