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

# optional imports – если есть хранилище/миграции
try:
    from crypto_ai_bot.core.storage.sqlite_adapter import connect
except Exception:  # pragma: no cover
    connect = None  # type: ignore

try:
    from crypto_ai_bot.core.storage.migrations import runner as mig_runner  # type: ignore
except Exception:  # pragma: no cover
    mig_runner = None  # type: ignore

from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate

app = FastAPI(title="crypto-ai-bot")

_cfg: Settings | None = None
_bus: Bus | None = None
_broker = None
_start_ts = time.time()


@app.on_event("startup")
async def on_startup() -> None:
    global _cfg, _bus, _broker
    _cfg = Settings.build()
    log.init()
    _bus = Bus(max_queue=getattr(_cfg, "EVENT_QUEUE_MAX", 1000),
               backpressure=getattr(_cfg, "EVENT_BACKPRESSURE", "block"))
    _broker = create_broker(_cfg, bus=_bus)  # ← передаём шину в брокера
    metrics.inc("app_start_total", {"mode": _cfg.MODE})
    metrics.inc("broker_created_total", {"mode": _cfg.MODE})


@app.on_event("shutdown")
async def on_shutdown() -> None:
    try:
        close = getattr(_broker, "close", None)
        if callable(close):
            await asyncio.to_thread(close)
    except Exception:
        pass


def _db_health(cfg: Settings) -> Dict[str, Any]:
    if connect is None or not getattr(cfg, "DB_PATH", None):
        return {"status": "skipped", "latency_ms": 0}

    t0 = time.perf_counter()
    try:
        with connect(cfg.DB_PATH) as con:
            con.execute("SELECT 1").fetchone()
        return {"status": "ok", "latency_ms": int((time.perf_counter() - t0) * 1000)}
    except Exception as e:  # pragma: no cover
        return {"status": f"error:{type(e).__name__}", "latency_ms": int((time.perf_counter() - t0) * 1000)}


def _migrations_health(cfg: Settings) -> Dict[str, Any]:
    if connect is None or mig_runner is None or not getattr(cfg, "DB_PATH", None):
        return {"status": "skipped", "pending": None}

    try:
        with connect(cfg.DB_PATH) as con:
            # пробуем обнаружить схему версионирования
            row = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            ).fetchone()
            if not row:
                return {"status": "unknown", "pending": "unknown"}

            # если у runner есть API статуса — используем
            if hasattr(mig_runner, "get_status"):
                st = mig_runner.get_status(con)  # type: ignore[attr-defined]
                return {"status": st.get("status", "unknown"), "pending": st.get("pending")}
            if hasattr(mig_runner, "latest_version"):
                cur = con.execute("SELECT version FROM schema_version").fetchone()
                cur_v = int(cur[0]) if cur else 0
                latest_v = int(mig_runner.latest_version())  # type: ignore[attr-defined]
                pending = max(0, latest_v - cur_v)
                return {"status": "ok" if pending == 0 else "degraded", "pending": pending}
            # fallback
            return {"status": "unknown", "pending": "unknown"}
    except Exception as e:  # pragma: no cover
        return {"status": f"error:{type(e).__name__}", "pending": "unknown"}


@app.get("/health")
async def health() -> JSONResponse:
    cfg = _cfg  # type: ignore[assignment]
    assert cfg is not None
    bus = _bus
    assert bus is not None

    # DB + migrations
    db_status = _db_health(cfg)
    mig_status = _migrations_health(cfg)

    # broker ping
    br_status: Dict[str, Any] = {"status": "ok", "latency_ms": 0}
    t0 = time.perf_counter()
    try:
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
    except Exception as e:  # pragma: no cover
        time_status = {"status": f"error:{type(e).__name__}", "drift_ms": None, "limit_ms": cfg.TIME_DRIFT_LIMIT_MS}

    # bus health
    try:
        bus_h = bus.health()
    except Exception:  # pragma: no cover
        bus_h = {"status": "unknown"}

    components = {
        "mode": cfg.MODE,
        "db": db_status,
        "migrations": mig_status,
        "broker": br_status,
        "time": time_status,
        "bus": bus_h,
    }

    # простая матрица состояний
    critical = any(str(c.get("status", "")).startswith("error") for c in [db_status, br_status])
    degraded = (
        str(time_status.get("status")) == "degraded"
        or str(mig_status.get("status")) == "degraded"
        or str(bus_h.get("status")) == "degraded"
    )

    if critical:
        status, degradation_level = "unhealthy", "major"
    elif degraded:
        status, degradation_level = "degraded", "minor"
    else:
        status, degradation_level = "healthy", "none"

    return JSONResponse(
        {
            "status": status,
            "degradation_level": degradation_level,
            "uptime_sec": int(time.time() - _start_ts),
            "components": components,
        }
    )


@app.get("/metrics")
async def metrics_endpoint() -> PlainTextResponse:
    return PlainTextResponse(metrics.export(), media_type="text/plain; version=0.0.4; charset=utf-8")


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
