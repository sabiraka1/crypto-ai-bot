from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
import contextlib
from contextlib import asynccontextmanager
import time
from typing import Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container_async
from crypto_ai_bot.core.application import events_topics
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import export_text, hist, inc
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("app.server")
_container: Any | None = None


# -------- rate limiter --------
class RateLimiter:
    def __init__(self, limit_per_min: int = 10) -> None:
        self.limit = int(limit_per_min)
        self.bucket: dict[str, list[float]] = {}

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


def limit(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        request: Request | None = None
        for a in args:
            if isinstance(a, Request):
                request = a
                break
        if request is None:
            request = kwargs.get("request")
        if isinstance(request, Request) and not _rl.allow(request):
            inc(
                "http_requests_total",
                path="rate_limited",
                method=getattr(request, "method", "GET"),
                code="429",
            )
            raise HTTPException(status_code=429, detail="Too Many Requests")
        return await fn(*args, **kwargs)

    return wrapper


# -------- helper functions --------
async def _shutdown_orchestrators(orchs: dict[str, Any]) -> None:
    if not isinstance(orchs, dict):
        return
    tasks = []
    for oc in orchs.values():
        if hasattr(oc, "stop") and callable(oc.stop):
            tasks.append(asyncio.create_task(oc.stop()))
        else:
            _log.error("orchestrator_stop_schedule_failed", extra={"orch": oc})
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _shutdown_bus(bus: Any) -> None:
    if not bus:
        return
    if hasattr(bus, "stop") and callable(bus.stop):
        await bus.stop()
    elif hasattr(bus, "close") and callable(bus.close):
        await bus.close()


async def _shutdown_broker(broker: Any) -> None:
    exch = getattr(broker, "exchange", None) if broker else None
    if exch and hasattr(exch, "close") and callable(exch.close):
        await exch.close()


# -------- lifespan --------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _container
    _log.info("lifespan_start")
    _container = await build_container_async()

    try:
        yield
    finally:
        _log.info("lifespan_shutdown_begin")

        try:
            inst_lock = getattr(_container, "instance_lock", None)
            if inst_lock and hasattr(inst_lock, "release"):
                inst_lock.release()
        except Exception:
            _log.debug("instance_lock_release_failed", exc_info=True)

        try:
            orchs = getattr(_container, "orchestrators", None)
            await _shutdown_orchestrators(orchs)
        except Exception:
            _log.error("orchestrators_stop_failed", exc_info=True)

        try:
            bus = getattr(_container, "bus", None)
            await _shutdown_bus(bus)
        except Exception:
            _log.error("bus_shutdown_failed", exc_info=True)

        try:
            broker = getattr(_container, "broker", None)
            await _shutdown_broker(broker)
        except Exception:
            _log.error("exchange_close_failed", exc_info=True)

        _log.info("lifespan_shutdown_end")


app = FastAPI(lifespan=lifespan)
router = APIRouter()


# -------- HTTP metrics middleware --------
@app.middleware("http")
async def _metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    path = request.url.path
    method = request.method
    t = hist("http_request_latency_seconds", path=path, method=method)

    with t.time() if t else contextlib.nullcontext():
        response = await call_next(request)

    inc("http_requests_total", path=path, method=method, code=str(response.status_code))
    return response


# -------- endpoints: orchestrator --------
@router.post("/orchestrator/{name}/start")
@limit
async def orch_start(name: str, request: Request) -> JSONResponse:
    orch = getattr(_container, "orchestrators", {}).get(name) if _container else None
    if not orch:
        raise HTTPException(status_code=404, detail=f"Orchestrator {name} not found")
    try:
        await orch.start()
        return JSONResponse({"status": "started", "name": name})
    except Exception as exc:
        _log.error("orchestrator_start_failed", extra={"name": name, "error": str(exc)}, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start orchestrator")


@router.post("/orchestrator/{name}/stop")
@limit
async def orch_stop(name: str, request: Request) -> JSONResponse:
    orch = getattr(_container, "orchestrators", {}).get(name) if _container else None
    if not orch:
        raise HTTPException(status_code=404, detail=f"Orchestrator {name} not found")
    try:
        await orch.stop()
        return JSONResponse({"status": "stopped", "name": name})
    except Exception as exc:
        _log.error("orchestrator_stop_failed", extra={"name": name, "error": str(exc)}, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to stop orchestrator")


@router.get("/orchestrator/{name}/status")
@limit
async def orch_status(name: str, request: Request) -> JSONResponse:
    orch = getattr(_container, "orchestrators", {}).get(name) if _container else None
    if not orch:
        raise HTTPException(status_code=404, detail=f"Orchestrator {name} not found")
    try:
        st = await orch.status()
        return JSONResponse({"status": "ok", "orchestrator": name, "details": st})
    except Exception as exc:
        _log.error("orchestrator_status_failed", extra={"name": name, "error": str(exc)}, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch status")


# -------- endpoints: telegram webhook --------
@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    update: dict[str, Any] = Body(...),
) -> JSONResponse:
    bus = getattr(_container, "bus", None)
    if not bus:
        raise HTTPException(status_code=500, detail="Bus not initialized")

    try:
        await bus.publish(events_topics.TELEGRAM_UPDATE, update)
        return JSONResponse({"ok": True})
    except Exception as exc:
        _log.error("telegram_webhook_failed", extra={"error": str(exc)}, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process telegram update")


# -------- endpoints: health & metrics --------
@router.get("/health")
async def health() -> JSONResponse:
    try:
        return JSONResponse({"status": "ok", "ts": now_ms()})
    except Exception as exc:
        _log.error("health_failed", extra={"error": str(exc)}, exc_info=True)
        raise HTTPException(status_code=500, detail="Health check failed")


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    try:
        return PlainTextResponse(export_text())
    except Exception as exc:
        _log.error("metrics_failed", extra={"error": str(exc)}, exc_info=True)
        raise HTTPException(status_code=500, detail="Metrics export failed")


# -------- endpoints: pnl --------
@router.get("/pnl/today")
@limit
async def pnl_today(request: Request) -> JSONResponse:
    try:
        trades_repo = getattr(_container, "storage", None).trades if _container else None
        if not trades_repo or not hasattr(trades_repo, "daily_pnl_quote"):
            raise HTTPException(status_code=500, detail="Trades repo not available")
        pnl = trades_repo.daily_pnl_quote()
        return JSONResponse({"status": "ok", "pnl_today_quote": str(pnl)})
    except Exception as exc:
        _log.error("pnl_today_failed", extra={"error": str(exc)}, exc_info=True)
        raise HTTPException(status_code=500, detail="PNL calculation failed")


# -------- register router --------
app.include_router(router)
