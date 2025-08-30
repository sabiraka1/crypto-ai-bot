from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.metrics import render_prometheus, render_metrics_json
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.exceptions import (
    TradingError,
    ValidationError,
    BrokerError,
    TransientError,
    IdempotencyError,
    CircuitOpenError,
)
from crypto_ai_bot.app.compose import build_container

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

    # Жёсткое требование токена для API в live-режиме, если включён флаг
    try:
        require_token = bool(int(getattr(_container.settings, "REQUIRE_API_TOKEN_IN_LIVE", 0)))
    except Exception:
        require_token = False
    if (_container.settings.MODE or "").lower() == "live" and require_token:
        if not (_container.settings.API_TOKEN or "").strip():
            _container = None
            raise RuntimeError("API token is required in LIVE mode (set REQUIRE_API_TOKEN_IN_LIVE=1)")

    # --- Стартовый reconcile-барьер ---
    try:
        tol = dec(str(getattr(_container.settings, "RECONCILE_READY_TOLERANCE_BASE", "0.00000010")))
        pos = _container.storage.positions.get_position(_container.settings.SYMBOL)
        bal = await _container.broker.fetch_balance(_container.settings.SYMBOL)
        diff = (bal.free_base or dec("0")) - (pos.base_qty or dec("0"))
        
        if abs(diff) > tol:
            if bool(getattr(_container.settings, "RECONCILE_AUTOFIX", 0)):
                # Автоматическое выравнивание позиции
                add_rec = getattr(_container.storage.trades, "add_reconciliation_trade", None)
                if callable(add_rec):
                    add_rec({
                        "symbol": _container.settings.SYMBOL,
                        "side": ("buy" if diff > 0 else "sell"),
                        "amount": str(abs(diff)),
                        "status": "reconciliation",
                        "ts_ms": now_ms(),
                        "client_order_id": f"reconcile-start-{_container.settings.SYMBOL}-{now_ms()}",
                    })
                _container.storage.positions.set_base_qty(_container.settings.SYMBOL, bal.free_base or dec("0"))
                _log.info("startup_reconcile_autofix_applied", extra={
                    "symbol": _container.settings.SYMBOL,
                    "diff": str(diff),
                    "local_before": str(pos.base_qty),
                    "exchange": str(bal.free_base)
                })
            else:
                # Блокировка запуска при расхождении
                _log.error("startup_reconcile_blocked", extra={
                    "symbol": _container.settings.SYMBOL,
                    "expected": str(bal.free_base), 
                    "local": str(pos.base_qty),
                    "diff": str(diff)
                })
                raise RuntimeError(
                    f"Position mismatch at startup: exchange={bal.free_base} local={pos.base_qty}. "
                    f"Enable RECONCILE_AUTOFIX=1 or fix manually."
                )
        else:
            _log.info("startup_reconcile_ok", extra={
                "symbol": _container.settings.SYMBOL,
                "position": str(pos.base_qty),
                "diff": str(diff)
            })
    except RuntimeError:
        # Пробрасываем RuntimeError для остановки
        raise
    except Exception as exc:
        _log.error("startup_reconcile_failed", extra={"error": str(exc)})
        # Не стартуем торговлю и даём 503 на /ready
        return

    # Автостарт оркестратора
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
    status = _container.orchestrator.status()
    # Добавляем информацию о паузе если она есть
    if hasattr(_container.orchestrator, '_paused'):
        status['paused'] = _container.orchestrator._paused
    return {"ok": True, "status": status}


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


# ---- Ручная пауза/резюм ----

@router.post("/orchestrator/pause")
async def orchestrator_pause(request: Request, _: Any = Depends(_auth)) -> Dict[str, Any]:
    """Приостановить выполнение торговых операций без остановки задач."""
    if not hasattr(_container.orchestrator, 'pause'):
        # Если метод не реализован, делаем простую установку флага
        _container.orchestrator._paused = True
        _log.info("orchestrator_paused_via_flag")
        return {"ok": True, "message": "paused_via_flag", "status": _container.orchestrator.status()}
    
    await _container.orchestrator.pause()
    return {"ok": True, "message": "paused", "status": _container.orchestrator.status()}


@router.post("/orchestrator/resume")
async def orchestrator_resume(request: Request, _: Any = Depends(_auth)) -> Dict[str, Any]:
    """Возобновить выполнение торговых операций."""
    if not hasattr(_container.orchestrator, 'resume'):
        # Если метод не реализован, снимаем флаг
        _container.orchestrator._paused = False
        _log.info("orchestrator_resumed_via_flag")
        return {"ok": True, "message": "resumed_via_flag", "status": _container.orchestrator.status()}
    
    await _container.orchestrator.resume()
    return {"ok": True, "message": "resumed", "status": _container.orchestrator.status()}


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
    rows = _container.storage.trades.list_today(_container.settings.SYMBOL)
    buys = sum(dec(str(r["cost"])) for r in rows if str(r["side"]).lower() == "buy")
    sells = sum(dec(str(r["cost"])) for r in rows if str(r["side"]).lower() == "sell")
    fees = sum(dec(str(r.get("fee_quote", 0))) for r in rows)
    realized = (sells - buys) - fees
    return {
        "symbol": _container.settings.SYMBOL,
        "total_trades": len(rows),
        "buys_quote": str(buys),
        "sells_quote": str(sells),
        "fees_quote": str(fees),
        "realized_quote": str(realized),
    }


app.include_router(router)