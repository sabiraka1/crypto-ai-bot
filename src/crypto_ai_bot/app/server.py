# src/crypto_ai_bot/app/server.py
from fastapi import FastAPI, Header, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from contextlib import asynccontextmanager
import anyio
import asyncio

from crypto_ai_bot.app.compose import build_container, Container

# --- Lifespan: корректный startup/shutdown ---
container: Container = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global container
    container = build_container()
    try:
        yield
    finally:
        # graceful: остановить шину, дождаться фоновых задач, закрыть БД
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

# --- Метрики/проброс остального оставляем как было ---
@app.get("/metrics")
def metrics():
    # предполагается, что utils.metrics уже экспонирует текст Prometheus
    from crypto_ai_bot.utils.metrics import export_prometheus
    return PlainTextResponse(export_prometheus(), media_type="text/plain; version=0.0.4")

# --- Health без блокировки event loop ---
@app.get("/health")
async def health():
    async def _probe():
        # брокер синхронный (CCXT): выполняем в thread-pool с таймаутом
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

# --- Простая защита webhook /telegram ---
RATE_BUCKET = {}  # {ip: (tokens, ts)}
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

@app.post("/telegram")
async def telegram(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    import time
    secret = container.settings.TELEGRAM_WEBHOOK_SECRET
    if secret and x_telegram_bot_api_secret_token != secret:
        raise HTTPException(status_code=403, detail="forbidden")
    # лимит размера
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")
    # rate limit per IP
    ip = request.client.host if request.client else "none"
    if not _rl_ok(ip, time.time()):
        raise HTTPException(status_code=429, detail="rate limited")

    # дальше — твоя текущая обработка обновлений Telegram
    from crypto_ai_bot.app.adapters.telegram import handle_update
    return await handle_update(app, body, container)
