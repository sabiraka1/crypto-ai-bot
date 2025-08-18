from contextlib import asynccontextmanager
from typing import Optional

import anyio
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container, Container
from crypto_ai_bot.utils.metrics import export_prometheus

# если у тебя уже есть файл app/tasks/reconciler.py (из прошлого шага),
# этот импорт будет работать; ниже я также приложу его «правильную» версию.
from crypto_ai_bot.app.tasks.reconciler import start_reconciler


# --- Глобальные ссылки контейнера и стоп-скоуп реконсилиатора ---
container: Optional[Container] = None
_stop_scope = None  # anyio.CancelScope из start_reconciler

# --- Rate limiting и лимит тела для /telegram ---
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Composition & lifecycle:
    - создаём контейнер зависимостей
    - запускаем реконсилиратор как фоновой таск
    - на остановке — корректно закрываемся
    """
    global container, _stop_scope
    container = build_container()

    # стартуем реконсилиратор (возвращает cancel_scope для graceful stop)
    _stop_scope = await start_reconciler(container)

    try:
        yield
    finally:
        # аккуратно гасим фоновую задачу
        try:
            if _stop_scope:
                _stop_scope.cancel()
        except Exception:
            pass

        # останавливаем шину событий
        try:
            if hasattr(container.bus, "stop"):
                container.bus.stop()
        except Exception:
            pass

        # закрываем соединение с БД
        try:
            container.con.close()
        except Exception:
            pass


app = FastAPI(lifespan=lifespan)


@app.get("/metrics")
def metrics():
    return PlainTextResponse(export_prometheus(), media_type="text/plain; version=0.0.4")


@app.get("/health")
async def health():
    """
    Health-check без блокировки event loop:
    CCXT-синхронные вызовы выполняем в thread-pool с тайм-аутом.
    """
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


@app.post("/telegram")
async def telegram(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None)
):
    """
    Webhook Telegram c секретом, rate-limit и лимитом на размер тела.
    """
    import time

    secret = container.settings.TELEGRAM_WEBHOOK_SECRET
    if secret and x_telegram_bot_api_secret_token != secret:
        raise HTTPException(status_code=403, detail="forbidden")

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")

    ip = request.client.host if request.client else "none"
    if not _rl_ok(ip, time.time()):
        raise HTTPException(status_code=429, detail="rate limited")

    # делегируем в адаптер Telegram
    from crypto_ai_bot.app.adapters.telegram import handle_update
    return await handle_update(app, body, container)
