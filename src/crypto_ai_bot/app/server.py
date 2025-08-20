# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.app.middleware import RequestIdMiddleware, RateLimitMiddleware
from crypto_ai_bot.utils.rate_limit import MultiLimiter, TokenBucket
from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)

# -------- Prometheus /metrics mount (если установлен prometheus_client) ----------
try:
    from prometheus_client import make_asgi_app  # type: ignore
    _PROM = True
except Exception:
    _PROM = False

# --------- DI Container in app.state --------------------------------------------
app = FastAPI(title="crypto-ai-bot", version="1.0.0")

# Входной rate-limit (общий для всего инстанса)
_ingress_limiter = MultiLimiter(
    buckets={
        "ingress": TokenBucket(capacity=60, refill_per_sec=6.0),  # ~60 r/m
    },
    default_bucket="ingress",
)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(RateLimitMiddleware, limiter=_ingress_limiter, bucket_name="ingress")

if _PROM:
    app.mount("/metrics", make_asgi_app())  # экспонируем метрики

# ------------------------ Lifespan: build container, start/stop ------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    c = build_container()
    app.state.container = c
    # Запускаем EventBus и Orchestrator
    await c.bus.start()
    await c.orchestrator.start()
    logger.info("Application started: mode=%s symbol=%s", c.settings.MODE, c.settings.SYMBOL)
    try:
        yield
    finally:
        # Корректная остановка
        try:
            await c.orchestrator.stop()
        except Exception as e:
            logger.error("orchestrator.stop failed: %s", e)
        try:
            await c.bus.stop()
        except Exception as e:
            logger.error("bus.stop failed: %s", e)
        logger.info("Application stopped.")

app.router.lifespan_context = lifespan  # bind lifespan

# ------------------------------- Health endpoints --------------------------------
@app.get("/health", tags=["meta"])
async def health() -> Dict[str, Any]:
    c = app.state.container
    return {
        "ok": True,
        "mode": c.settings.MODE,
        "exchange": c.settings.EXCHANGE,
        "symbol": c.settings.SYMBOL,
        "orchestrator_running": c.orchestrator.is_running,
        "bus_running": c.bus.is_running,
    }

@app.get("/", tags=["meta"])
async def root() -> Dict[str, str]:
    return {"name": "crypto-ai-bot", "status": "ok"}

# ------------------------------ Telegram webhook ---------------------------------
# Хендлер должен соответствовать: await handle_update(container, payload)
try:
    from crypto_ai_bot.app.adapters.telegram import handle_update as telegram_handle_update  # type: ignore
    _TELEGRAM_READY = True
except Exception as e:
    logger.warning("telegram adapter not available: %s", e)
    _TELEGRAM_READY = False

@app.get("/telegram", tags=["telegram"])
async def telegram_get(secret: str | None = None) -> Response:
    """
    Небольшая проверка доступности вебхука (GET — для быстрой ручной проверки).
    Для реальных обновлений используем POST /telegram/webhook.
    """
    if not _TELEGRAM_READY:
        return PlainTextResponse("telegram adapter not configured", status_code=501)

    c = app.state.container
    if secret and secret == c.settings.TELEGRAM_BOT_SECRET:
        return PlainTextResponse("ok", status_code=200)
    return PlainTextResponse("Method Not Allowed", status_code=405)

@app.post("/telegram/webhook", tags=["telegram"])
async def telegram_webhook(request: Request) -> Response:
    if not _TELEGRAM_READY:
        return PlainTextResponse("telegram adapter not configured", status_code=501)

    c = app.state.container
    # Простейшая защита вебхука секретом через ?secret=...
    secret = request.query_params.get("secret")
    if not secret or secret != c.settings.TELEGRAM_BOT_SECRET:
        return PlainTextResponse("forbidden", status_code=403)

    try:
        payload = await request.json()
    except Exception:
        # fallback: попытка прочитать сырое тело
        body = await request.body()
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as e:
            logger.warning("telegram payload parse failed: %s", e)
            return PlainTextResponse("bad payload", status_code=400)

    try:
        await telegram_handle_update(c, payload)
        return PlainTextResponse("ok", status_code=200)
    except Exception as e:
        logger.error("telegram handler failed: %s", e, extra={"payload": payload})
        return PlainTextResponse("error", status_code=500)

# ------------------------------- Extended status ---------------------------------
@app.get("/status/extended", tags=["meta"])
async def status_extended() -> JSONResponse:
    """
    Лёгкий расширенный статус — без тяжёлых операций, пригоден для внешнего мониторинга.
    """
    c = app.state.container
    body = {
        "mode": c.settings.MODE,
        "exchange": c.settings.EXCHANGE,
        "symbol": c.settings.SYMBOL,
        "perf_budgets_ms": {
            "eval_p99": c.settings.PERF_BUDGET_EVAL_P99_MS,
            "place_order_p99": c.settings.PERF_BUDGET_PLACE_ORDER_P99_MS,
            "reconcile_p99": c.settings.PERF_BUDGET_RECONCILE_P99_MS,
        },
        "bus": {"running": c.bus.is_running, "concurrency": c.bus.concurrency, "max_queue": c.bus.max_queue},
        "orchestrator": {"running": c.orchestrator.is_running},
    }
    return JSONResponse(body, status_code=status.HTTP_200_OK)
