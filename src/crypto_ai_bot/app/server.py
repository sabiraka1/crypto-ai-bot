from __future__ import annotations

import os
import time
from typing import Any, Dict, List

from fastapi import FastAPI, APIRouter, Request, Depends, HTTPException, Body
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from ..utils.logging import get_logger
from ..utils.metrics import render_prometheus, render_metrics_json, inc
from ..utils.time import now_ms
from .compose import build_container

_log = get_logger("server")

app = FastAPI(title="crypto-ai-bot", version="1.0.0")
app.state.container = build_container()

router = APIRouter()
security = HTTPBearer(auto_error=False)

# --- простейший rate-limit (in-memory per endpoint+ip) ------------------------
_RL: Dict[str, List[float]] = {}  # key -> timestamps


def rate_limit(key: str, max_calls: int, per_sec: float) -> None:
    now = time.monotonic()
    window_start = now - per_sec
    arr = _RL.setdefault(key, [])
    # drop old
    i = 0
    while i < len(arr) and arr[i] < window_start:
        i += 1
    if i:
        del arr[:i]
    if len(arr) >= max_calls:
        raise HTTPException(status_code=429, detail="Too Many Requests")
    arr.append(now)


async def auth_opt(credentials: HTTPAuthorizationCredentials = Depends(security)) -> None:
    """Bearer token (опционально). Если API_TOKEN задан — требуем совпадение."""
    token_required = os.getenv("API_TOKEN")
    if not token_required:
        return
    if not credentials:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if credentials.credentials != token_required:
        raise HTTPException(status_code=401, detail="Unauthorized")


# --- lifecycle ----------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    c = app.state.container
    _log.info("server_start", extra={"mode": c.settings.MODE, "symbol": c.settings.SYMBOL})
    # автозапуск оркестратора можно контролировать env/настройкой (по умолчанию не запускаем)
    if os.getenv("AUTO_START", "0") in {"1", "true", "yes"}:
        c.orchestrator.start()


@app.on_event("shutdown")
async def shutdown_event():
    c = app.state.container
    try:
        await c.orchestrator.stop()
    finally:
        await c.bus.close()
        try:
            c.storage.conn.close()
        except Exception:
            pass
    _log.info("server_stop")


# --- endpoints ----------------------------------------------------------------
@router.get("/health")
async def health() -> JSONResponse:
    c = app.state.container
    rep = await c.health.check(symbol=c.settings.SYMBOL)
    payload = {"ok": rep.ok, "ts_ms": rep.ts_ms, "components": rep.components}
    return JSONResponse(status_code=(200 if rep.ok else 503), content=payload)


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    try:
        return render_prometheus()
    except Exception:
        data = render_metrics_json()
        return "# metrics_fallback\n" + str(data) + "\n"


@router.get("/orchestrator/status")
async def orchestrator_status(_: Any = Depends(auth_opt)) -> Dict[str, Any]:
    c = app.state.container
    return {"ok": True, "status": c.orchestrator.status()}


@router.post("/orchestrator/start")
async def orchestrator_start(request: Request, _: Any = Depends(auth_opt)) -> Dict[str, Any]:
    rate_limit(f"start:{request.client.host}", max_calls=1, per_sec=60.0)
    c = request.app.state.container
    st = c.orchestrator.status()
    if st.get("running"):
        return {"ok": True, "message": "already_running", "status": st}
    c.orchestrator.start()
    return {"ok": True, "message": "started", "status": c.orchestrator.status()}


@router.post("/orchestrator/stop")
async def orchestrator_stop(request: Request, _: Any = Depends(auth_opt)) -> Dict[str, Any]:
    rate_limit(f"stop:{request.client.host}", max_calls=2, per_sec=60.0)
    c = request.app.state.container
    await c.orchestrator.stop()
    return {"ok": True, "message": "stopped", "status": c.orchestrator.status()}


@router.get("/positions")
async def get_positions(_: Any = Depends(auth_opt)) -> Dict[str, Any]:
    c = app.state.container
    pos = c.storage.positions.get_position(c.settings.SYMBOL)
    t = await c.broker.fetch_ticker(c.settings.SYMBOL)
    unreal = (t.last - (pos.avg_entry_price or 0)) * (pos.base_qty or 0)
    return {
        "symbol": c.settings.SYMBOL,
        "base_qty": str(pos.base_qty),
        "avg_price": str(pos.avg_entry_price),
        "current_price": str(t.last),
        "unrealized_pnl": str(unreal),
    }


@router.get("/trades")
async def get_trades(limit: int = 100, _: Any = Depends(auth_opt)) -> Dict[str, Any]:
    c = app.state.container
    rows = c.storage.trades.list_recent(c.settings.SYMBOL, limit)
    return {"trades": rows, "total": len(rows)}


@router.get("/performance")
async def performance(_: Any = Depends(auth_opt)) -> Dict[str, Any]:
    c = app.state.container
    trades = c.storage.trades.list_today(c.settings.SYMBOL)
    realized = sum(Decimal(r["cost"]) if r["side"] == "sell" else Decimal("0") for r in trades)  # грубо
    return {"total_trades": len(trades), "realized_quote": str(realized)}


app.include_router(router)
