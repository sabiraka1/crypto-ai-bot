from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Query
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
from crypto_ai_bot.utils.decimal import dec
from .compose import build_container

_log = get_logger("server")

app = FastAPI(title="crypto-ai-bot", version="1.0.0")
_container = None

router = APIRouter()
security = HTTPBearer(auto_error=False)


def _get_orch(symbol: str):
    sym = symbol or _container.settings.SYMBOL
    if sym == "all":
        return None
    orch = _container.orchestrators.get(sym)
    if not orch:
        raise HTTPException(404, f"orchestrator for symbol={sym} not found")
    return orch

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

    # требование токена в live (по флагу)
    try:
        require_token = bool(int(getattr(_container.settings, "REQUIRE_API_TOKEN_IN_LIVE", 0)))
    except Exception:
        require_token = False
    if (_container.settings.MODE or "").lower() == "live" and require_token:
        if not (_container.settings.API_TOKEN or "").strip():
            _container = None
            raise RuntimeError("API token is required in LIVE mode (set REQUIRE_API_TOKEN_IN_LIVE=1)")

    # стартовый reconcile-барьер для каждого символа
    try:
        tol = dec(str(getattr(_container.settings, "RECONCILE_READY_TOLERANCE_BASE", "0.00000010")))
        for sym, orch in _container.orchestrators.items():
            pos = _container.storage.positions.get_position(sym)
            bal = await orch.broker.fetch_balance(sym)
            diff = (bal.free_base or dec("0")) - (pos.base_qty or dec("0"))
            if abs(diff) > tol:
                if bool(getattr(_container.settings, "RECONCILE_AUTOFIX", 0)):
                    add_rec = getattr(_container.storage.trades, "add_reconciliation_trade", None)
                    if callable(add_rec):
                        add_rec({
                            "symbol": sym,
                            "side": ("buy" if diff > 0 else "sell"),
                            "amount": str(abs(diff)),
                            "status": "reconciliation",
                            "ts_ms": now_ms(),
                            "client_order_id": f"reconcile-start-{sym}-{now_ms()}",
                        })
                    _container.storage.positions.set_base_qty(sym, dec(str(bal.free_base)))
                    adder = getattr(_container.storage.audit, "add", None)
                    if callable(adder):
                        try: adder("reconcile.autofix_startup", {"symbol": sym, "new_local_base": str(bal.free_base), "ts_ms": now_ms()})
                        except Exception: pass
                    _log.info("startup_reconcile_autofix_applied", extra={"diff": str(diff), "symbol": sym})
                else:
                    adder = getattr(_container.storage.audit, "add", None)
                    if callable(adder):
                        try: adder("reconcile.blocked_startup", {"symbol": sym, "exchange": str(bal.free_base),
                                                                 "local": str(pos.base_qty), "ts_ms": now_ms()})
                        except Exception: pass
                    _log.error("startup_reconcile_blocked", extra={"expected": str(bal.free_base), "local": str(pos.base_qty), "symbol": sym})
                    raise RuntimeError(
                        f"[{sym}] Position mismatch at startup: exchange={bal.free_base} local={pos.base_qty}. "
                        f"Enable RECONCILE_AUTOFIX=1 or fix manually."
                    )
    except Exception as exc:
        _log.error("startup_reconcile_failed", extra={"error": str(exc)})

    autostart = bool(_container.settings.TRADER_AUTOSTART) or _container.settings.MODE == "live"
    if autostart:
        loop = asyncio.get_running_loop()
        for sym, orch in _container.orchestrators.items():
            loop.call_soon(orch.start)
        _log.info("orchestrators_autostart_enabled", extra={"symbols": list(_container.orchestrators.keys())})


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _container:
        try:
            tasks = []
            for orch in _container.orchestrators.values():
                st = orch.status()
                if st.get("running"):
                    tasks.append(orch.stop())
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            _log.info("orchestrators_stopped_on_shutdown")
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
        # готов, если хоть один орк жив и health.ok
        oks = []
        for sym, orch in _container.orchestrators.items():
            rep = await _container.health.check(symbol=sym)
            oks.append(rep.ok)
        ok = any(oks)
        return JSONResponse(status_code=(200 if ok else 503), content={"ok": ok, "symbols": list(_container.orchestrators.keys())})
    except Exception as exc:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    try:
        return render_prometheus()
    except Exception:
        data = render_metrics_json()
        return "#metrics_fallback\n" + str(data) + "\n"


# -------- orchestrators control --------

@router.get("/orchestrator/list")
async def orchestrator_list(_: Any = Depends(_auth)) -> Dict[str, Any]:
    sts = {sym: o.status() for sym, o in _container.orchestrators.items()}
    return {"ok": True, "symbols": list(_container.orchestrators.keys()), "status": sts}

@router.get("/orchestrator/status")
async def orchestrator_status(symbol: str = Query(None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    if symbol == "all":
        sts = {sym: o.status() for sym, o in _container.orchestrators.items()}
        return {"ok": True, "status": sts}
    orch = _get_orch(symbol)
    return {"ok": True, "status": orch.status()}

@router.post("/orchestrator/start")
async def orchestrator_start(symbol: str = Query(None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    if symbol == "all":
        for o in _container.orchestrators.values():
            if not o.status().get("running"):
                o.start()
        return {"ok": True, "message": "started_all"}
    orch = _get_orch(symbol)
    if orch.status().get("running"):
        return {"ok": True, "message": "already_running"}
    orch.start()
    return {"ok": True, "message": "started"}

@router.post("/orchestrator/stop")
async def orchestrator_stop(symbol: str = Query(None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    if symbol == "all":
        await asyncio.gather(*[o.stop() for o in _container.orchestrators.values()], return_exceptions=True)
        return {"ok": True, "message": "stopped_all"}
    orch = _get_orch(symbol)
    await orch.stop()
    return {"ok": True, "message": "stopped"}

@router.post("/orchestrator/pause")
async def orchestrator_pause(symbol: str = Query(None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    if symbol == "all":
        await asyncio.gather(*[o.pause() for o in _container.orchestrators.values()], return_exceptions=True)
        return {"ok": True, "message": "paused_all"}
    orch = _get_orch(symbol)
    await orch.pause()
    return {"ok": True, "message": "paused", "status": orch.status()}

@router.post("/orchestrator/resume")
async def orchestrator_resume(symbol: str = Query(None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    if symbol == "all":
        await asyncio.gather(*[o.resume() for o in _container.orchestrators.values()], return_exceptions=True)
        return {"ok": True, "message": "resumed_all"}
    orch = _get_orch(symbol)
    await orch.resume()
    return {"ok": True, "message": "resumed", "status": orch.status()}


# -------- read-only views (per symbol) --------

@router.get("/positions")
async def get_positions(symbol: str = Query(None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    sym = symbol or _container.settings.SYMBOL
    pos = _container.storage.positions.get_position(sym)
    t = await _container.broker.fetch_ticker(sym) if _container.settings.MODE == "live" else await _container.orchestrators[sym].broker.fetch_ticker(sym)
    unreal = (t.last - (pos.avg_entry_price or dec("0"))) * (pos.base_qty or dec("0"))
    return {
        "symbol": sym,
        "base_qty": str(pos.base_qty or dec("0")),
        "avg_price": str(pos.avg_entry_price or dec("0")),
        "current_price": str(t.last),
        "unrealized_pnl": str(unreal),
    }

@router.get("/trades")
async def get_trades(symbol: str = Query(None), limit: int = 100, _: Any = Depends(_auth)) -> Dict[str, Any]:
    sym = symbol or _container.settings.SYMBOL
    rows = _container.storage.trades.list_recent(sym, limit)
    return {"symbol": sym, "trades": rows, "total": len(rows)}

@router.get("/performance")
async def performance(symbol: str = Query(None), _: Any = Depends(_auth)) -> Dict[str, Any]:
    sym = symbol or _container.settings.SYMBOL
    rows = _container.storage.trades.list_today(sym)
    buys = sum(dec(r["cost"]) for r in rows if str(r["side"]).lower() == "buy")
    sells = sum(dec(r["cost"]) for r in rows if str(r["side"]).lower() == "sell")
    fees  = sum(dec(r.get("fee_quote") or 0) for r in rows)
    realized = (sells - buys) - fees
    return {
        "symbol": sym,
        "total_trades": len(rows),
        "buys_quote": str(buys),
        "sells_quote": str(sells),
        "fees_quote": str(fees),
        "realized_quote": str(realized),
    }

app.include_router(router)
