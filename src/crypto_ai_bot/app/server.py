from __future__ import annotations

import time
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional, Dict

from fastapi import FastAPI, APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container_async  # ВАЖНО: именно *_async
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import export_text

# pydantic-валидация конфигурации (опционально)
try:
    from crypto_ai_bot.core.infrastructure.settings_schema import validate_settings
except Exception:
    validate_settings = None

_log = get_logger("app.server")
_container: Optional[Any] = None


class RateLimiter:
    def __init__(self, limit_per_min: int = 10) -> None:
        self.limit = int(limit_per_min)
        self.bucket: Dict[str, list[float]] = {}

    def _key(self, request: Request) -> str:
        ip = request.client.host if request.client else "unknown"
        tok = request.headers.get("authorization", "")
        return f"{ip}|{tok}"

    def allow(self, request: Request) -> bool:
        now = time.time()
        k = self._key(request)
        q = self.bucket.setdefault(k, [])
        while q and q[0] < now - 60.0:
            q.pop(0)
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


_rl = RateLimiter(limit_per_min=10)


def limit(fn: Callable):
    async def wrapper(*args, **kwargs):
        request: Optional[Request] = None
        for a in args:
            if isinstance(a, Request):
                request = a
                break
        if request is None:
            request = kwargs.get("request")

        if isinstance(request, Request) and not _rl.allow(request):
            raise HTTPException(status_code=429, detail="Too Many Requests")
        return await fn(*args, **kwargs)
    return wrapper


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _container
    _log.info("lifespan_start")
    _container = await build_container_async()
    try:
        if validate_settings:
            validate_settings(getattr(_container, "settings", None))
    except Exception as exc:
        _log.error("settings_validation_failed", extra={"error": str(exc)})

    try:
        yield
    finally:
        _log.info("lifespan_shutdown_begin")
        try:
            orch = getattr(_container, "orchestrator", None)
            if orch is not None:
                await orch.stop()
        except Exception as exc:
            _log.error("orchestrator_stop_failed", extra={"error": str(exc)})

        try:
            bus = getattr(_container, "bus", None)
            if bus and hasattr(bus, "close"):
                await bus.close()
        except Exception as exc:
            _log.error("bus_close_failed", extra={"error": str(exc)})

        try:
            broker = getattr(_container, "broker", None)
            exch = getattr(broker, "exchange", None) if broker else None
            if exch and hasattr(exch, "close"):
                await exch.close()
        except Exception as exc:
            _log.error("exchange_close_failed", extra={"error": str(exc)})
        _log.info("lifespan_shutdown_end")


app = FastAPI(lifespan=lifespan)
router = APIRouter()


def _ctx_or_500():
    if _container is None:
        raise HTTPException(status_code=503, detail="Container not ready")
    return _container


@router.get("/health")
async def health():
    try:
        c = _ctx_or_500()
        settings = getattr(c, "settings", None)
        symbol = getattr(settings, "SYMBOL", "BTC/USDT") if settings else "BTC/USDT"
        return JSONResponse({"ok": True, "symbol": symbol})
    except HTTPException:
        raise
    except Exception as exc:
        _log.error("health_failed", extra={"error": str(exc)})
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.get("/metrics")
async def metrics():
    try:
        return PlainTextResponse(export_text(), media_type="text/plain; version=0.0.4")
    except Exception as exc:
        _log.error("metrics_failed", extra={"error": str(exc)})
        return PlainTextResponse("", status_code=500)


@router.get("/orchestrator/status")
async def orch_status():
    c = _ctx_or_500()
    orch = getattr(c, "orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=500, detail="orchestrator_missing")
    try:
        return JSONResponse(orch.status())
    except Exception as exc:
        _log.error("orch_status_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="status_failed")


@router.post("/orchestrator/start")
@limit
async def orch_start(request: Request):
    c = _ctx_or_500()
    orch = getattr(c, "orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=500, detail="orchestrator_missing")
    try:
        await orch.start()
        return JSONResponse({"ok": True, "status": orch.status()})
    except Exception as exc:
        _log.error("orch_start_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="start_failed")


@router.post("/orchestrator/stop")
@limit
async def orch_stop(request: Request):
    c = _ctx_or_500()
    orch = getattr(c, "orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=500, detail="orchestrator_missing")
    try:
        await orch.stop()
        return JSONResponse({"ok": True, "status": orch.status()})
    except Exception as exc:
        _log.error("orch_stop_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="stop_failed")


@router.post("/orchestrator/pause")
@limit
async def orch_pause(request: Request):
    c = _ctx_or_500()
    orch = getattr(c, "orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=500, detail="orchestrator_missing")
    try:
        await orch.pause()
        return JSONResponse({"ok": True, "status": orch.status()})
    except Exception as exc:
        _log.error("orch_pause_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="pause_failed")


@router.post("/orchestrator/resume")
@limit
async def orch_resume(request: Request):
    c = _ctx_or_500()
    orch = getattr(c, "orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=500, detail="orchestrator_missing")
    try:
        await orch.resume()
        return JSONResponse({"ok": True, "status": orch.status()})
    except Exception as exc:
        _log.error("orch_resume_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="resume_failed")


app.include_router(router)
