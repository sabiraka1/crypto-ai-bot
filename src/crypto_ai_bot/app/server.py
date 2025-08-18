from contextlib import asynccontextmanager
from typing import Optional

import anyio
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container, Container
from crypto_ai_bot.utils.metrics import export as export_metrics   # <-- фикс
from crypto_ai_bot.app.tasks.reconciler import start_reconciler

container: Optional[Container] = None
_stop_scope = None

RATE_BUCKET = {}
MAX_BODY_BYTES = 64_000
RPS = 2.0
BURST = 5

def _rl_ok(ip: str, now: float) -> bool:
    import time
    tokens, ts = RATE_BUCKET.get(ip, (BURST, now))
    tokens = min(BURST, tokens + (now - ts) * RPS)
    if tokens < 1.0:
        RATE_BUCKET[ip] = (tokens, now)
        return False
    RATE_BUCKET[ip] = (tokens - 1.0, now)
    return True

@asynccontextmanager
async def lifespan(app: FastAPI):
    global container, _stop_scope
    container = build_container()
    _stop_scope = await start_reconciler(container)
    try:
        yield
    finally:
        try:
            if _stop_scope:
                _stop_scope.cancel()
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
    return PlainTextResponse(export_metrics(), media_type="text/plain; version=0.0.4")  # <-- фикс

@app.get("/health")
async def health():
    async def _probe():
        def _call():
            try:
                t = container.broker.fetch_ticker(container.settings.SYMBOL)
                return bool(t)
            except Exception:
                return False
        return await anyio.to_thread.run_sync(_call)
    with anyio.move_on_after(2.0) as scope:
        ok = await _probe()
    if not scope.cancel_called and ok:
        return {"status": "ok"}
    return JSONResponse({"status": "degraded"}, status_code=503)

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
    import time
    secret = getattr(container.settings, "TELEGRAM_WEBHOOK_SECRET", None)
    if secret and x_telegram_bot_api_secret_token != secret:
        raise HTTPException(status_code=403, detail="forbidden")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")
    ip = request.client.host if request.client else "none"
    if not _rl_ok(ip, time.time()):
        raise HTTPException(status_code=429, detail="rate limited")
    from crypto_ai_bot.app.adapters.telegram import handle_update
    return await handle_update(app, body, container)
