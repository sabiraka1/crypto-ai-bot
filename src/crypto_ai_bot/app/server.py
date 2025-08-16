# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.encoders import jsonable_encoder

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.utils import metrics

# Если есть утилита синхронизации времени — опционально
try:
    from crypto_ai_bot.utils import time_sync
except Exception:  # не падаем, если нет
    time_sync = None  # type: ignore


app = FastAPI(title="Crypto AI Bot", version="v1")


# -------------------- lifecycle --------------------
@app.on_event("startup")
def _startup() -> None:
    # Конфиг один раз
    cfg = Settings.build()
    app.state.cfg = cfg

    # Брокер один раз (factory поддерживает MODE: live/paper/backtest)
    app.state.broker = create_broker(cfg)

    metrics.inc("app_start_total", {"mode": getattr(cfg, "MODE", "paper")})


# -------------------- helpers --------------------
def _ok(x: bool) -> str:
    return "ok" if x else "error"


# -------------------- health --------------------
@app.get("/health")
def health() -> JSONResponse:
    cfg = app.state.cfg
    broker = app.state.broker

    components: Dict[str, Dict[str, Any]] = {"mode": getattr(cfg, "MODE", "paper")}
    status = "healthy"
    degradation = "none"

    # DB ping (здесь просто имитация, чтобы не требовать БД)
    t0 = time.perf_counter()
    db_ok = True
    db_latency = int((time.perf_counter() - t0) * 1000)
    components["db"] = {"status": _ok(db_ok), "latency_ms": db_latency}

    # broker ping
    try:
        t0 = time.perf_counter()
        _ = broker.fetch_ticker(getattr(cfg, "SYMBOL", "BTC/USDT"))
        br_lat = int((time.perf_counter() - t0) * 1000)
        components["broker"] = {"status": "ok", "latency_ms": br_lat}
    except Exception as e:
        status = "degraded"
        degradation = "major"
        components["broker"] = {"status": f"error:{type(e).__name__}", "detail": str(e), "latency_ms": 0}

    # time drift (если доступно)
    drift_ms = None
    drift_status = "unknown"
    if time_sync and hasattr(time_sync, "get_cached_drift_ms"):
        try:
            drift_ms = int(time_sync.get_cached_drift_ms(default=0))
            limit = int(getattr(cfg, "TIME_DRIFT_MAX_MS", 1500))
            drift_ok = drift_ms <= limit
            components["time"] = {"status": _ok(drift_ok), "drift_ms": drift_ms, "limit_ms": limit}
            if not drift_ok:
                status = "degraded"
                degradation = "major"
        except Exception as e:
            components["time"] = {"status": f"error:{type(e).__name__}", "detail": str(e)}

    return JSONResponse({"status": status, "degradation_level": degradation, "components": components})


# -------------------- metrics --------------------
@app.get("/metrics")
def metrics_export() -> PlainTextResponse:
    # Prometheus формат
    return PlainTextResponse(metrics.export(), media_type="text/plain; version=0.0.4")


# -------------------- tick (evaluate + optional execute) --------------------
@app.post("/tick")
async def tick(request: Request) -> JSONResponse:
    """
    Безопасный обработчик:
    - Всегда код 200 (даже при ошибках) — внутри есть status="error".
    - Никаких необработанных исключений → не будет 500.
    - Если репозитории/БД не подключены, выполняется только EVALUATE (без EXECUTE).
    """
    cfg = app.state.cfg
    broker = app.state.broker

    try:
        payload = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            payload = await request.json()
    except Exception:
        payload = {}

    symbol = payload.get("symbol") if isinstance(payload, dict) else None
    timeframe = payload.get("timeframe") if isinstance(payload, dict) else None
    limit = payload.get("limit") if isinstance(payload, dict) else None

    # Импорт здесь, чтобы уменьшить риск циклов при старте
    try:
        from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute
    except Exception as e:
        # если что-то не импортировалось — возвращаем читаемую ошибку
        body = {"status": "error", "error": f"import_failed: {type(e).__name__}: {e}"}
        return JSONResponse(jsonable_encoder(body))

    # В этой минимальной сборке репозитории/UnitOfWork не прокидываем → только evaluation
    try:
        result = uc_eval_and_execute(
            cfg,
            broker,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            positions_repo=None,
            trades_repo=None,
            audit_repo=None,
            uow=None,
            idempotency_repo=None,
        )
        return JSONResponse(jsonable_encoder(result))
    except Exception as e:
        body = {"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"}
        return JSONResponse(jsonable_encoder(body))
