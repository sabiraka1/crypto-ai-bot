from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.events import AsyncBus as Bus
from crypto_ai_bot.utils import metrics, logging as log
from crypto_ai_bot.utils.time_sync import measure_time_drift
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate

# ──────────────────────────────────────────────────────────────────────────────
# Глобальные объекты приложения
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="crypto-ai-bot")

_cfg: Settings | None = None
_bus: Bus | None = None
_broker = None  # создаётся фабрикой
_start_ts = time.time()

# ──────────────────────────────────────────────────────────────────────────────
# Старт/стоп
# ──────────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup() -> None:
    global _cfg, _bus, _broker
    _cfg = Settings.build()
    log.init()  # структурный логгер с trace_id, если уже реализован
    _bus = Bus(max_queue=_cfg.EVENT_QUEUE_MAX, backpressure=_cfg.EVENT_BACKPRESSURE)  # AsyncBus
    _broker = create_broker(_cfg)  # фабрика (live | paper | backtest)
    metrics.inc("app_start_total", {"mode": _cfg.MODE})
    metrics.inc("broker_created_total", {"mode": _cfg.MODE})


@app.on_event("shutdown")
async def on_shutdown() -> None:
    # если у брокера есть close/cleanup — вызываем
    try:
        close = getattr(_broker, "close", None)
        if callable(close):
            await asyncio.to_thread(close)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> JSONResponse:
    cfg = _cfg  # type: ignore[assignment]
    assert cfg is not None
    bus = _bus
    assert bus is not None

    # DB ping (опционально, если БД уже сконфигурена в проекте)
    db_status = {"status": "ok", "latency_ms": 0}
    try:
        # здесь может быть: with connect(cfg.DB_PATH) as con: con.execute("SELECT 1")
        pass
    except Exception as e:
        db_status = {"status": f"error:{type(e).__name__}", "latency_ms": 0}

    # broker ping
    br_status: Dict[str, Any] = {"status": "ok", "latency_ms": 0}
    try:
        t0 = time.perf_counter()
        await asyncio.to_thread(_broker.fetch_ticker, cfg.SYMBOL)  # короткий вызов
        br_status["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    except Exception as e:
        br_status = {"status": f"error:{type(e).__name__}", "latency_ms": int((time.perf_counter() - t0) * 1000)}  # type: ignore[name-defined]

    # time drift
    time_status = {"status": "ok", "drift_ms": 0, "limit_ms": cfg.TIME_DRIFT_LIMIT_MS}
    try:
        from crypto_ai_bot.utils.http_client import get_http_client
        drift = measure_time_drift(cfg, get_http_client())
        time_status["drift_ms"] = int(drift or 0)
        if drift is not None and drift > cfg.TIME_DRIFT_LIMIT_MS:
            time_status["status"] = "degraded"
    except Exception as e:
        time_status = {"status": f"error:{type(e).__name__}", "drift_ms": None, "limit_ms": cfg.TIME_DRIFT_LIMIT_MS}

    # общая оценка (простая матрица)
    components = {"mode": cfg.MODE, "db": db_status, "broker": br_status, "time": time_status}
    status = "healthy"
    if "error" in str(db_status["status"]).lower() or "error" in str(br_status["status"]).lower():
        status = "unhealthy"
    elif str(time_status["status"]).lower() == "degraded":
        status = "degraded"

    degradation_level = "none" if status == "healthy" else ("major" if status == "unhealthy" else "minor")

    return JSONResponse(
        {
            "status": status,
            "degradation_level": degradation_level,
            "uptime_sec": int(time.time() - _start_ts),
            "components": components,
        }
    )


# ──────────────────────────────────────────────────────────────────────────────
# Prometheus metrics
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/metrics")
async def metrics_endpoint() -> PlainTextResponse:
    return PlainTextResponse(metrics.export(), media_type="text/plain; version=0.0.4; charset=utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Ручной тик (без размещения ордера)
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/tick")
async def tick(request: Request) -> JSONResponse:
    cfg = _cfg  # type: ignore[assignment]
    assert cfg is not None
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    symbol = body.get("symbol", cfg.SYMBOL)
    timeframe = body.get("timeframe", cfg.TIMEFRAME)
    limit = int(body.get("limit", cfg.LIMIT_BARS))

    try:
        decision = uc_evaluate(cfg, _broker, symbol=symbol, timeframe=timeframe, limit=limit)
        return JSONResponse({"status": "evaluated", "symbol": symbol, "timeframe": timeframe, "decision": decision})
    except Exception as e:
        metrics.inc("tick_error_total", {"type": type(e).__name__})
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"})
