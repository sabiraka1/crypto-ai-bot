from __future__ import annotations
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
import asyncio
import time

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container_async
from crypto_ai_bot.core.application import (
    events_topics as EVT,  # noqa: N812  # нужен в /health и alertmanager/webhook
)
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
            inc("http_requests_total", path="rate_limited", method=getattr(request, "method", "GET"), code="429")
            raise HTTPException(status_code=429, detail="Too Many Requests")
        return await fn(*args, **kwargs)
    return wrapper

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
            orchs = getattr(_container, "orchestrators", None)
            if isinstance(orchs, dict):
                tasks = []
                for oc in orchs.values():
                    try:
                        tasks.append(asyncio.create_task(oc.stop()))
                    except Exception:  # noqa: BLE001
                        _log.error("orchestrator_stop_schedule_failed", exc_info=True)
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:  # noqa: BLE001
            _log.error("orchestrators_stop_failed", exc_info=True)

        try:
            bus = getattr(_container, "bus", None)
            # безопасный shutdown шины: сначала stop(), если нет — close()
            if bus and hasattr(bus, "stop"):
                await bus.stop()
            elif bus and hasattr(bus, "close"):
                await bus.close()
        except Exception:  # noqa: BLE001
            _log.error("bus_shutdown_failed", exc_info=True)

        try:
            broker = getattr(_container, "broker", None)
            exch = getattr(broker, "exchange", None) if broker else None
            if exch and hasattr(exch, "close"):
                await exch.close()
        except Exception:  # noqa: BLE001
            _log.error("exchange_close_failed", exc_info=True)
        _log.info("lifespan_shutdown_end")

app = FastAPI(lifespan=lifespan)
router = APIRouter()

# -------- HTTP metrics middleware --------
@app.middleware("http")
async def _metrics_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    path = request.url.path
    method = request.method
    t = hist("http_request_latency_seconds", path=path, method=method)
    if t:
        with t.time():
            response = await call_next(request)
    else:
        response = await call_next(request)
    inc("http_requests_total", path=path, method=method, code=str(response.status_code))
    return response

def _ctx_or_500() -> Any:
    if _container is None:
        raise HTTPException(status_code=503, detail="Container not ready")
    return _container

def _get_orchestrator(symbol: str | None) -> tuple[Any, str]:
    c = _ctx_or_500()
    s = getattr(c, "settings", None)
    default_symbol = getattr(s, "SYMBOL", "BTC/USDT") if s else "BTC/USDT"
    sym = (symbol or default_symbol)
    orchs = getattr(c, "orchestrators", None)
    if not isinstance(orchs, dict):
        raise HTTPException(status_code=500, detail="orchestrators_missing")
    orch = orchs.get(sym) or orchs.get(sym.replace("-", "/").upper())
    if orch is None:
        raise HTTPException(status_code=404, detail=f"orchestrator_not_found_for_{sym}")
    return orch, sym

# -------- helpers --------
async def _call_with_timeout(coro, *, timeout: float = 2.5):  # noqa: ASYNC109
    return await asyncio.wait_for(coro, timeout=timeout)

# -------- endpoints --------
@router.get("/health")
async def health() -> JSONResponse:
    """
    Детальная проверка health: DB, EventBus, Broker (с таймаутами).
    Быстрый путь — в memory-only. Публикуем событие в шину.
    Возвращаем также удобные поля (default_symbol, symbols) для интерфейса.
    """
    ok = True
    details: dict[str, Any] = {"ts_ms": now_ms()}

    try:
        c = _ctx_or_500()
    except HTTPException:
        return JSONResponse({"ok": False, "error": "container_not_ready"}, status_code=503)  # noqa: TRY300

    settings = getattr(c, "settings", None)
    default_symbol = getattr(settings, "SYMBOL", "BTC/USDT") if settings else "BTC/USDT"
    symbols = list(getattr(c, "orchestrators", {}).keys())

    bus = getattr(c, "bus", None)
    storage = getattr(c, "storage", None)
    broker = getattr(c, "broker", None)

    # DB check
    try:
        if storage and hasattr(storage, "ping"):
            await _call_with_timeout(storage.ping(), timeout=1.5)
            details["db"] = "ok"
        else:
            details["db"] = "n/a"
    except Exception as exc:  # noqa: BLE001
        ok = False
        details["db"] = f"fail: {exc!s}"

    # EventBus check
    try:
        if bus and hasattr(bus, "publish"):
            await _call_with_timeout(bus.publish("health.ping", {"ts_ms": now_ms()}), timeout=1.0)
            details["bus"] = "ok"
        else:
            details["bus"] = "n/a"
    except Exception as exc:  # noqa: BLE001
        ok = False
        details["bus"] = f"fail: {exc!s}"

    # Broker check (облегчённый)
    try:
        if broker and hasattr(broker, "get_balance"):
            await _call_with_timeout(broker.get_balance(), timeout=2.0)
            details["broker"] = "ok"
        else:
            details["broker"] = "n/a"
    except Exception as exc:  # noqa: BLE001
        ok = False
        details["broker"] = f"fail: {exc!s}"

    # публикация события в шину (для наблюдаемости/Telegram)
    if bus and hasattr(bus, "publish"):
        try:
            await bus.publish(EVT.HEALTH_REPORT, {"ok": ok, **details})
        except Exception:  # noqa: BLE001
            _log.debug("health_bus_publish_failed", exc_info=True)

    body = {"ok": ok, "default_symbol": default_symbol, "symbols": symbols, **details}
    return JSONResponse(body, status_code=200 if ok else 500)

@router.post("/alertmanager/webhook")
async def alertmanager_webhook(payload: dict = Body(...)) -> JSONResponse:
    """
    Webhook от Alertmanager -> перенаправляем в EventBus на EVT.ALERTS_ALERTMANAGER.
    Нужен для телеграм-алёртов и общего мониторинга.
    """
    try:
        c = _ctx_or_500()
    except HTTPException:
        return JSONResponse({"ok": False, "error": "container_not_ready"}, status_code=503)  # noqa: TRY300

    bus = getattr(c, "bus", None)
    if bus and hasattr(bus, "publish"):
        try:
            await bus.publish(EVT.ALERTS_ALERTMANAGER, {"payload": payload, "ts_ms": now_ms()})
        except Exception:  # noqa: BLE001
            _log.debug("alert_bus_publish_failed", exc_info=True)
    return JSONResponse({"ok": True})  # noqa: TRY300

@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    try:
        return PlainTextResponse(export_text(), media_type="text/plain; version=0.0.4")  # noqa: TRY300
    except Exception:  # noqa: BLE001
        _log.error("metrics_failed", exc_info=True)
        return PlainTextResponse("", status_code=500)  # noqa: TRY300

@router.get("/orchestrator/status")
async def orch_status(symbol: str | None = Query(default=None)) -> JSONResponse:
    orch, sym = _get_orchestrator(symbol)
    try:
        st = orch.status()
        st["symbol"] = sym
        return JSONResponse(st)  # noqa: TRY300
    except Exception as e:  # noqa: BLE001
        _log.error("orch_status_failed", extra={"symbol": sym}, exc_info=True)
        raise HTTPException(status_code=500, detail="status_failed") from e

@router.post("/orchestrator/start")
@limit
async def orch_start(request: Request, symbol: str | None = Query(default=None)) -> JSONResponse:
    orch, sym = _get_orchestrator(symbol)
    try:
        await orch.start()
        st = orch.status()
        st["symbol"] = sym
        return JSONResponse({"ok": True, "status": st})  # noqa: TRY300
    except Exception as e:  # noqa: BLE001
        _log.error("orch_start_failed", extra={"symbol": sym}, exc_info=True)
        raise HTTPException(status_code=500, detail="start_failed") from e

@router.post("/orchestrator/stop")
@limit
async def orch_stop(request: Request, symbol: str | None = Query(default=None)) -> JSONResponse:
    orch, sym = _get_orchestrator(symbol)
    try:
        await orch.stop()
        st = orch.status()
        st["symbol"] = sym
        return JSONResponse({"ok": True, "status": st})  # noqa: TRY300
    except Exception as e:  # noqa: BLE001
        _log.error("orch_stop_failed", extra={"symbol": sym}, exc_info=True)
        raise HTTPException(status_code=500, detail="stop_failed") from e

@router.post("/orchestrator/pause")
@limit
async def orch_pause(request: Request, symbol: str | None = Query(default=None)) -> JSONResponse:
    orch, sym = _get_orchestrator(symbol)
    try:
        await orch.pause()
        st = orch.status()
        st["symbol"] = sym
        return JSONResponse({"ok": True, "status": st})  # noqa: TRY300
    except Exception as e:  # noqa: BLE001
        _log.error("orch_pause_failed", extra={"symbol": sym}, exc_info=True)
        raise HTTPException(status_code=500, detail="pause_failed") from e

@router.post("/orchestrator/resume")
@limit
async def orch_resume(request: Request, symbol: str | None = Query(default=None)) -> JSONResponse:
    orch, sym = _get_orchestrator(symbol)
    try:
        await orch.resume()
        st = orch.status()
        st["symbol"] = sym
        return JSONResponse({"ok": True, "status": st})  # noqa: TRY300
    except Exception as e:  # noqa: BLE001
        _log.error("orch_resume_failed", extra={"symbol": sym}, exc_info=True)
        raise HTTPException(status_code=500, detail="resume_failed") from e

@router.get("/pnl/today")
async def pnl_today(symbol: str | None = Query(default=None)) -> JSONResponse:
    """
    ЕДИНЫЙ источник истины — репозиторий трейдов:
    daily_pnl_quote / daily_turnover_quote / count_orders_today.
    Без запасных обходов.
    """
    c = _ctx_or_500()
    try:
        _, sym = _get_orchestrator(symbol)
        st = getattr(c, "storage", None)
        if not st:
            raise HTTPException(status_code=500, detail="storage_missing")

        pnl_quote_str = "0"
        turnover_quote_str = "0"
        orders_count_int = 0

        if hasattr(st, "trades"):
            if hasattr(st.trades, "daily_pnl_quote"):
                try:
                    pnl_quote_str = str(st.trades.daily_pnl_quote(sym))
                except Exception:  # noqa: BLE001
                    _log.error("pnl_today_calc_failed", extra={"symbol": sym}, exc_info=True)
            else:
                _log.warning("pnl_today_missing_method_daily_pnl_quote", extra={"symbol": sym})

            if hasattr(st.trades, "daily_turnover_quote"):
                try:
                    turnover_quote_str = str(st.trades.daily_turnover_quote(sym))
                except Exception:  # noqa: BLE001
                    _log.error("turnover_today_calc_failed", extra={"symbol": sym}, exc_info=True)
            else:
                _log.warning("pnl_today_missing_method_daily_turnover_quote", extra={"symbol": sym})

            if hasattr(st.trades, "count_orders_today"):
                try:
                    orders_count_int = int(st.trades.count_orders_today(sym))
                except Exception:  # noqa: BLE001
                    _log.error("orders_today_count_failed", extra={"symbol": sym}, exc_info=True)
            else:
                _log.warning("pnl_today_missing_method_count_orders_today", extra={"symbol": sym})

        return JSONResponse(
            {"symbol": sym, "pnl_quote": pnl_quote_str, "turnover_quote": turnover_quote_str, "orders_count": orders_count_int}
        )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        _log.error("pnl_today_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="pnl_today_failed")

@router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> JSONResponse:
    """Webhook endpoint Telegram-бота (можно использовать вместо polling)."""
    try:
        _ = await request.body()
        data = await request.json()
        c = _ctx_or_500()
        settings = getattr(c, "settings", None)
        secret = getattr(settings, "TELEGRAM_BOT_SECRET", "")

        if secret:
            provided_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if provided_token != secret:
                _log.warning("telegram_webhook_invalid_secret")
                return JSONResponse({"ok": False}, status_code=401)

        _log.debug("telegram_webhook_received", extra={"update_id": data.get("update_id")})
        # если нужно — передать в tg_bot.process_webhook_update(data)
        return JSONResponse({"ok": True})
    except Exception:  # noqa: BLE001
        _log.error("telegram_webhook_error", exc_info=True)
        return JSONResponse({"ok": False}, status_code=500)

app.include_router(router)
