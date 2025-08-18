from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Optional
import asyncio

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container, Container
from crypto_ai_bot.utils.logging import setup_json_logging
from crypto_ai_bot.utils.metrics import export as export_metrics, inc
from crypto_ai_bot.app.tasks.reconciler import start_reconciler
from crypto_ai_bot.app.middleware import register_middlewares
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils.time_sync import measure_time_drift_ms
from crypto_ai_bot.core.storage.sqlite_maint import run_scheduled_maintenance

container: Optional[Container] = None
_reconciler_task: Optional[asyncio.Task] = None
_housekeeping_task: Optional[asyncio.Task] = None
_cb_health = CircuitBreaker(failure_threshold=3, reset_timeout_sec=5.0, success_threshold=1)

async def _housekeeping_loop():
    """
    Раз в минуту:
      - чистим просроченную идемпотентность
      - по расписанию запускаем SQLite maintenance (quick/full)
    """
    while True:
        try:
            if container:
                # idempotency cleanup
                try:
                    if hasattr(container, "idempotency_repo"):
                        removed = container.idempotency_repo.cleanup_expired()
                        if removed:
                            inc("idempotency_cleanup_removed", {})
                except Exception:
                    pass

                # db maintenance
                try:
                    mtype, dur = run_scheduled_maintenance(container.con, container.settings)
                    if mtype != "skip":
                        inc("db_maint_run", {"type": mtype})
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global container, _reconciler_task, _housekeeping_task
    container = build_container()

    # JSON-логи + middleware
    setup_json_logging(container.settings)
    register_middlewares(app, container.settings)

    # фоновый reconciler
    try:
        _reconciler_task = start_reconciler(container)
    except Exception:
        _reconciler_task = None

    # housekeeping (idempotency + sqlite maint)
    _housekeeping_task = asyncio.create_task(_housekeeping_loop())

    try:
        yield
    finally:
        # аккуратное завершение
        for t in (_housekeeping_task, _reconciler_task):
            try:
                if t:
                    t.cancel()
            except Exception:
                pass
        try:
            if hasattr(container.bus, "stop"):
                container.bus.stop()
        except Exception:
            pass
        try:
            container.con.close()
        except Exception:
            pass

app = FastAPI(lifespan=lifespan)

@app.get("/metrics")
def metrics():
    return PlainTextResponse(export_metrics(), media_type="text/plain; version=0.0.4")

@app.get("/health")
async def health():
    """
    Компонентный health: broker, db, bus, time_sync + degradation_level и статистика CB.
    """
    details = {}
    ok_components = 0
    total = 4

    # broker (неблокирующий вызов)
    async def _probe_broker():
        try:
            from asyncio import to_thread
            def _fetch():
                try:
                    t = container.broker.fetch_ticker(container.settings.SYMBOL)
                    return bool(t)
                except Exception as e:
                    try:
                        _cb_health.call(lambda: (_ for _ in ()).throw(e))
                    except Exception:
                        pass
                    return False
            return await to_thread(_fetch)
        except Exception:
            return False

    if _cb_health.state == "OPEN":
        b_ok = False
    else:
        try:
            b_ok = await asyncio.wait_for(_probe_broker(), timeout=2.0)
        except Exception:
            b_ok = False
    details["broker"] = bool(b_ok); ok_components += int(b_ok)

    # db
    try:
        uv = container.con.execute("PRAGMA user_version;").fetchone()
        details["db"] = True if uv is not None else False
        ok_components += int(details["db"])
    except Exception:
        details["db"] = False

    # bus
    try:
        hb = container.bus.health() if hasattr(container.bus, "health") else {"running": True}
        details["bus"] = bool(hb.get("running", True))
        ok_components += int(details["bus"])
    except Exception:
        details["bus"] = False

    # time sync
    try:
        drift_ms = measure_time_drift_ms(container)
        max_drift = int(getattr(container.settings, "MAX_TIME_DRIFT_MS", 5000))
        td_ok = drift_ms <= max_drift
        details["time_drift_ms"] = drift_ms
        details["time_sync"] = td_ok
        ok_components += int(td_ok)
    except Exception:
        details["time_sync"] = False

    degr = int(round((1 - ok_components / total) * 100))
    status = "ok" if degr == 0 else ("degraded" if degr < 100 else "unhealthy")
    details["degradation_level"] = degr
    details["circuit"] = _cb_health.get_stats()

    return JSONResponse({"status": status, **details}, status_code=(200 if status == "ok" else 503))

@app.get("/status/extended")
def status_extended():
    try:
        bus_h = container.bus.health() if hasattr(container.bus, "health") else {"running": True, "dlq_size": None}
    except Exception:
        bus_h = {"running": False, "dlq_size": None}
    try:
        pending = container.trades_repo.count_pending()
    except Exception:
        pending = None
    try:
        uv = container.con.execute("PRAGMA user_version;").fetchone()
        user_version = int(uv[0]) if uv and len(uv) > 0 else 0
    except Exception:
        user_version = None
    return {
        "exchange": getattr(container.settings, "EXCHANGE", "unknown"),
        "symbol": getattr(container.settings, "SYMBOL", "unknown"),
        "bus": bus_h,
        "pending_orders": pending,
        "db_user_version": user_version,
    }

@app.post("/telegram")
async def telegram(request: Request, x_telegram_bot_api_secret_token: Optional[str] = Header(default=None)):
    secret = getattr(container.settings, "TELEGRAM_WEBHOOK_SECRET", None)
    if secret and x_telegram_bot_api_secret_token != secret:
        raise HTTPException(status_code=403, detail="forbidden")

    body = await request.body()
    from crypto_ai_bot.app.adapters.telegram import handle_update
    return await handle_update(app, body, container)
