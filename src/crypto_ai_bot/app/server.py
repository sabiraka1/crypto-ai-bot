from contextlib import asynccontextmanager
from typing import Optional

import anyio
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container, Container
from crypto_ai_bot.utils.logging import setup_json_logging
from crypto_ai_bot.utils.metrics import export as export_metrics
from crypto_ai_bot.app.tasks.reconciler import start_reconciler
from crypto_ai_bot.app.middleware import register_middlewares
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker

container: Optional[Container] = None
_reconciler = None
_cb_health = CircuitBreaker(failure_threshold=3, reset_timeout_sec=5.0, success_threshold=1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global container, _reconciler
    container = build_container()

    # JSON-логи
    setup_json_logging(container.settings)
    # Мидлвары (rate/body/logging/request-id)
    register_middlewares(app, container.settings)

    # старт фонового реконсилятора
    _reconciler = start_reconciler(container)

    try:
        yield
    finally:
        # аккуратное завершение
        try:
            if _reconciler:
                _reconciler.cancel()
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
    Быстрый healthcheck брокера с Circuit Breaker'ом и таймаутом.
    """
    def _probe_sync():
        if _cb_health.state == "OPEN":
            return False
        def _call():
            try:
                t = container.broker.fetch_ticker(container.settings.SYMBOL)
                return bool(t)
            except Exception as e:
                return _cb_health.call(lambda: (_ for _ in ()).throw(e))
        try:
            ok = _cb_health.call(lambda: _call())
            return bool(ok)
        except Exception:
            return False

    with anyio.move_on_after(2.0) as scope:
        ok = await anyio.to_thread.run_sync(_probe_sync)
    if not scope.cancel_called and ok:
        return {"status": "ok", "circuit": _cb_health.state}
    return JSONResponse({"status": "degraded", "circuit": _cb_health.state}, status_code=503)

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
    """
    Безопасный webhook:
      - секрет в заголовке (если настроен)
      - lim/body-лимиты и логирование обеспечиваются мидлварами
    """
    secret = getattr(container.settings, "TELEGRAM_WEBHOOK_SECRET", None)
    if secret and x_telegram_bot_api_secret_token != secret:
        raise HTTPException(status_code=403, detail="forbidden")

    body = await request.body()
    from crypto_ai_bot.app.adapters.telegram import handle_update
    return await handle_update(app, body, container)
