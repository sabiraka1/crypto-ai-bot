from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.core.application.use_cases.eval_and_execute import eval_and_execute

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.metrics import render_prometheus, render_metrics_json, inc
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.exceptions import (
    TradingError, RateLimitError, IdempotencyError, BrokerError, TransientError, CircuitOpenError,
)

_log = get_logger("server")

app = FastAPI(title="crypto-ai-bot", version="1.0.0")
router = APIRouter()
security = HTTPBearer(auto_error=False)

_container = None
_startup_blocked_reason: Optional[str] = None
_ip_allow: List[str] = []

# ---------- middleware: IP allowlist ----------
@app.middleware("http")
async def ip_allowlist_mw(request: Request, call_next):
    global _ip_allow
    if _container and (_container.settings.MODE or "").lower() == "live":
        if _ip_allow:
            ip = request.client.host if request.client else ""
            if ip not in _ip_allow:
                _log.warning("forbidden_ip", extra={"ip": ip})
                return JSONResponse(status_code=403, content={"ok": False, "error": "Forbidden"})
    return await call_next(request)


# ---------- auth ----------
async def _auth(_: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> None:
    if not _container:
        raise HTTPException(status_code=503, detail="Service Unavailable")
    token_required = (_container.settings.API_TOKEN or "").strip()
    if not token_required:
        return
    if not credentials or credentials.credentials != token_required:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------- app lifecycle ----------
@app.on_event("startup")
async def _startup() -> None:
    global _container, _startup_blocked_reason, _ip_allow
    _container = build_container()
    _startup_blocked_reason = None

    # IP allowlist
    raw = (getattr(_container.settings, "API_IP_ALLOWLIST", "") or "").strip()
    _ip_allow = [x.strip() for x in raw.split(",") if x.strip()]

    # требование токена в live-режиме (при флаге)
    require_token = False
    try:
        require_token = bool(int(getattr(_container.settings, "REQUIRE_API_TOKEN_IN_LIVE", 0)))
    except Exception:
        require_token = False
    if (_container.settings.MODE or "").lower() == "live" and require_token:
        if not (_container.settings.API_TOKEN or "").strip():
            _startup_blocked_reason = "API token is required in LIVE mode (set REQUIRE_API_TOKEN_IN_LIVE=1)"
            _log.error("startup_blocked_no_api_token")
            raise RuntimeError(_startup_blocked_reason)

    # стартовая сверка позиций (dec)
    try:
        symbols: List[str] = list(_container.orchestrators.keys()) or [_container.settings.SYMBOL]
        for sym in symbols:
            pos = _container.storage.positions.get_position(sym)
            bal = await _container.broker.fetch_balance(sym)
            tol = dec(str(getattr(_container.settings, "RECONCILE_READY_TOLERANCE_BASE", "0.00000010")))
            diff = (bal.free_base or dec("0")) - (pos.base_qty or dec("0"))
            if abs(diff) > tol:
                if bool(getattr(_container.settings, "RECONCILE_AUTOFIX", 0)):
                    add_rec = getattr(_container.storage.trades, "add_reconciliation_trade", None)
                    if callable(add_rec):
                        add_rec({"symbol": sym,"side": ("buy" if diff > 0 else "sell"),"amount": str(abs(diff)),
                                 "status": "reconciliation","ts_ms": now_ms(),"client_order_id": f"reconcile-start-{sym}-{now_ms()}"})
                    _container.storage.positions.set_base_qty(sym, bal.free_base or dec("0"))
                    _log.info("startup_reconcile_autofix_applied", extra={"symbol": sym, "exchange": str(bal.free_base), "local": str(pos.base_qty), "diff": str(diff)})
                else:
                    _startup_blocked_reason = (
                        f"Position mismatch at startup for {sym}: exchange={bal.free_base} local={pos.base_qty}. "
                        f"Enable RECONCILE_AUTOFIX=1 or fix manually."
                    )
                    _log.error("startup_reconcile_blocked", extra={"symbol": sym, "exchange": str(bal.free_base), "local": str(pos.base_qty), "diff": str(diff)})
                    raise RuntimeError(_startup_blocked_reason)
            else:
                _log.info("startup_reconcile_ok", extra={"symbol": sym, "position": str(pos.base_qty), "diff": str(diff)})
    except RuntimeError:
        raise
    except Exception as exc:
        _startup_blocked_reason = f"startup_reconcile_failed: {exc}"
        _log.error("startup_reconcile_failed", extra={"error": str(exc)})

    # автозапуск
    autostart = bool(_container.settings.TRADER_AUTOSTART) or (_container.settings.MODE or "").lower() == "live"
    if autostart and _container:
        loop = asyncio.get_running_loop()
        for sym, orch in _container.orchestrators.items():
            loop.call_soon(orch.start)
        _log.info("orchestrators_autostarted", extra={"symbols": list(_container.orchestrators.keys())})

@app.on_event("shutdown")
async def _shutdown() -> None:
    if not _container:
        return
    try:
        await asyncio.gather(*(orch.stop() for orch in _container.orchestrators.values()), return_exceptions=True)
    except Exception as exc:
        _log.error("shutdown_stop_failed", extra={"error": str(exc)})
    try:
        if getattr(_container, "lock", None):
            _container.lock.release()
    except Exception:
        pass
    _log.info("shutdown_ok")


# ---------- error mapping ----------
@app.exception_handler(TradingError)
async def trading_error_handler(_: Request, exc: TradingError):
    if isinstance(exc, RateLimitError):
        code = 429
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
async def unhandled_error_handler(_: Request, exc: Exception):
    _log.error("unhandled_error", extra={"error": str(exc)})
    return JSONResponse(status_code=500, content={"ok": False, "error": "InternalServerError"})


# ---------- health / metrics ----------
@router.get("/")
async def root() -> Dict[str, Any]:
    return {"name": "crypto-ai-bot", "version": "1.0.0"}

@router.get("/live")
async def live() -> Dict[str, Any]:
    return {"ok": True, "ts_ms": now_ms()}

@router.get("/ready")
async def ready() -> JSONResponse:
    if (not _container) or (_startup_blocked_reason is not None):
        detail = _startup_blocked_reason or "Container not ready"
        return JSONResponse(status_code=503, content={"ok": False, "detail": detail})
    return JSONResponse(status_code=200, content={"ok": True, "ts_ms": now_ms()})

@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    try:
        return render_prometheus()
    except Exception:
        data = render_metrics_json()
        return "#metrics_fallback\n" + str(data) + "\n"


# ---------- orchestrators ----------
def _pick_symbols(symbol: Optional[str]) -> List[str]:
    if not _container:
        return []
    if symbol is None or symbol == "":
        return [_container.settings.SYMBOL]
    if symbol.lower() == "all":
        return list(_container.orchestrators.keys())
    if symbol not in _container.orchestrators:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol}")
    return [symbol]

@router.get("/orchestrator/status")
async def orchestrator_status(symbol: Optional[str] = Query(default=None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    syms = _pick_symbols(symbol)
    status = {s: _container.orchestrators[s].status() for s in syms}
    return {"ok": True, "status": status}

@router.post("/orchestrator/start")
async def orchestrator_start(symbol: Optional[str] = Query(default=None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    for s in _pick_symbols(symbol):
        if not _container.orchestrators[s].status().get("running"):
            _container.orchestrators[s].start()
    return {"ok": True, "message": "started", "symbols": _pick_symbols(symbol)}

@router.post("/orchestrator/stop")
async def orchestrator_stop(symbol: Optional[str] = Query(default=None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    await asyncio.gather(*(_container.orchestrators[s].stop() for s in _pick_symbols(symbol)))
    return {"ok": True, "message": "stopped", "symbols": _pick_symbols(symbol)}

@router.post("/orchestrator/pause")
async def orchestrator_pause(symbol: Optional[str] = Query(default=None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    await asyncio.gather(*(_container.orchestrators[s].pause() for s in _pick_symbols(symbol)))
    return {"ok": True, "message": "paused", "symbols": _pick_symbols(symbol)}

@router.post("/orchestrator/resume")
async def orchestrator_resume(symbol: Optional[str] = Query(default=None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    await asyncio.gather(*(_container.orchestrators[s].resume() for s in _pick_symbols(symbol)))
    return {"ok": True, "message": "resumed", "symbols": _pick_symbols(symbol)}


# ---------- positions & pnl ----------
@router.get("/positions")
async def get_positions(symbol: Optional[str] = Query(default=None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    syms = _pick_symbols(symbol)
    res: Dict[str, Dict[str, str]] = {}
    for s in syms:
        pos = _container.storage.positions.get_position(s)
        t = await _container.broker.fetch_ticker(s)
        unreal = (t.last - (pos.avg_entry_price or dec("0"))) * (pos.base_qty or dec("0"))
        res[s] = {
            "base_qty": str(pos.base_qty or dec("0")),
            "avg_price": str(pos.avg_entry_price or dec("0")),
            "current_price": str(t.last),
            "unrealized_quote": str(unreal),
        }
    return {"ok": True, "positions": res}

@router.get("/pnl/today")
async def pnl_today(symbol: Optional[str] = Query(default=None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    syms = _pick_symbols(symbol)
    res: Dict[str, Dict[str, str]] = {}
    for s in syms:
        rows = _container.storage.trades.list_today(s)
        from crypto_ai_bot.utils.decimal import dec
        buys = sum(dec(str(r["cost"])) for r in rows if str(r["side"]).lower() == "buy")
        sells = sum(dec(str(r["cost"])) for r in rows if str(r["side"]).lower() == "sell")
        fees = sum(dec(str(r.get("fee_quote", 0))) for r in rows)
        realized = (sells - buys) - fees
        res[s] = {
            "total_trades": str(len(rows)),
            "buys_quote": str(buys),
            "sells_quote": str(sells),
            "fees_quote": str(fees),
            "realized_quote": str(realized),
        }
    return {"ok": True, "pnl": res}


# ---------- manual trade trigger ----------
@router.post("/trade/force")
async def trade_force(
    action: str = Query(..., regex="^(buy|sell|hold)$"),
    symbol: Optional[str] = Query(default=None),
    quote_amount: Optional[str] = Query(default=None),
    _: Any = Depends(_auth),
) -> Dict[str, Any]:
    s = _pick_symbols(symbol)[0]
    order = await eval_and_execute(
        symbol=s,
        storage=_container.storage,
        broker=_container.broker,
        bus=_container.bus,
        exchange=_container.settings.EXCHANGE,
        fixed_quote_amount=dec(str(quote_amount or _container.settings.FIXED_AMOUNT)),
        idempotency_bucket_ms=_container.settings.IDEMPOTENCY_BUCKET_MS,
        idempotency_ttl_sec=_container.settings.IDEMPOTENCY_TTL_SEC,
        force_action=action,
        risk_manager=_container.risk,
        protective_exits=_container.exits,
        settings=_container.settings,
        fee_estimate_pct=_container.settings.FEE_PCT_ESTIMATE,
    )
    return {"ok": True, "symbol": s, "order": None if not order else {
        "id": order.id, "client_order_id": order.client_order_id, "side": order.side,
        "amount": str(order.amount), "price": str(order.price or ""), "cost": str(order.cost or ""),
        "fee_quote": str(getattr(order, "fee_quote", "")),
    }}

app.include_router(router)
