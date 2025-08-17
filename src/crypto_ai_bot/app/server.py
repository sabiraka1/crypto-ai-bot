# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order as uc_place_order

from crypto_ai_bot.core.events.async_bus import AsyncBus, BackpressurePolicy
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.logging import init as init_logging
from crypto_ai_bot.utils.http_client import get_http_client

# optional imports
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift, DEFAULT_TIME_SOURCES
except Exception:
    measure_time_drift = None  # type: ignore
    DEFAULT_TIME_SOURCES = []  # type: ignore

app = FastAPI(title="crypto-ai-bot")
init_logging()


class AppState:
    cfg: Settings
    broker: Any
    bus: AsyncBus
    http: Any
    started_ts: float


def _health_rollup(components: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Возвращает:
      - status: healthy | degraded | unhealthy
      - degradation_level: none | no_trading | critical
    Матрица (простая и прозрачная):
      - DB down → critical
      - Broker error → no_trading (если только брокер), critical (если вместе с DB)
      - Drift > limit → no_trading
      - Всё ок → none
    """
    db_ok = components["db"]["status"] == "ok"
    broker_ok = components["broker"]["status"] == "ok"
    drift_ok = components["time"]["status"] == "ok"

    # critical, если БД не ок — это база системы
    if not db_ok:
        return {"status": "unhealthy", "degradation_level": "critical"}

    # no_trading, если брокер не ок или дрейф времени превышен
    if not broker_ok or not drift_ok:
        return {"status": "degraded", "degradation_level": "no_trading"}

    return {"status": "healthy", "degradation_level": "none"}


@app.on_event("startup")
async def on_startup() -> None:
    app.state = AppState()  # type: ignore
    app.state.cfg = Settings.build()
    app.state.http = get_http_client()

    # Broker через фабрику (live/paper/backtest)
    app.state.broker = create_broker(app.state.cfg)

    # AsyncBus с backpressure и простой DLQ
    app.state.bus = AsyncBus(
        queue_size=getattr(app.state.cfg, "BUS_QUEUE_SIZE", 1000),
        backpressure_policy=BackpressurePolicy.DROP_OLDEST,
        dlq_enabled=True,
        dlq_max=1000,
    )
    await app.state.bus.start()

    # Gauge: когда стартовали
    metrics.inc("app_start_total", {"mode": app.state.cfg.MODE})
    app.state.started_ts = time.time()

    # если есть оркестратор — пусть он занимается периодикой;
    # если нет — лёгкий внутренний планировщик метрик/дрейфа.
    try:
        # «мягкий» импорт, чтобы не ломать, если оркестратор другой
        from crypto_ai_bot.core.orchestrator import get_global_orchestrator
        orch = get_global_orchestrator()
        if orch:
            # периодический refresh метрик/дрейфа пусть делает оркестратор
            orch.schedule_every(
                getattr(app.state.cfg, "METRICS_REFRESH_SEC", 30),
                _background_refresh_metrics,
            )
        else:
            _spawn_periodic_tasks()
    except Exception:
        _spawn_periodic_tasks()


def _spawn_periodic_tasks() -> None:
    # раз в 30с — refresh health-метрик (time drift, аптайм)
    async def _loop():
        while True:
            try:
                await _background_refresh_metrics()
            except Exception:
                pass
            await asyncio.sleep(30)

    asyncio.create_task(_loop())


async def _background_refresh_metrics() -> None:
    cfg: Settings = app.state.cfg
    # time drift
    if measure_time_drift:
        sources = cfg.TIME_DRIFT_URLS or DEFAULT_TIME_SOURCES
        try:
            drift_ms = await measure_time_drift(app.state.http, sources)
            metrics.set_gauge("time_drift_ms", float(drift_ms))
        except Exception:
            # ничего — дрейф может не помериться
            pass
    # uptime
    metrics.set_gauge("app_uptime_seconds", float(time.time() - app.state.started_ts))


@app.on_event("shutdown")
async def on_shutdown() -> None:
    try:
        await app.state.bus.stop()
    except Exception:
        pass


@app.get("/health")
async def health() -> Response:
    cfg: Settings = app.state.cfg

    # DB check
    db_start = time.time()
    db_res = {"status": "ok", "latency_ms": 0}
    try:
        con = connect(cfg.DB_PATH)
        con.execute("SELECT 1").fetchone()
        # миграции (если таблица есть, смотрим последнюю версию)
        try:
            row = con.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()
            db_res["schema_version"] = (row[0] if row and row[0] is not None else 0)  # type: ignore
        except Exception:
            db_res["schema_version"] = "unknown"  # type: ignore
        finally:
            con.close()
    except Exception as e:
        db_res["status"] = f"error:{type(e).__name__}"  # type: ignore
        db_res["detail"] = str(e)[:200]  # type: ignore
    finally:
        db_res["latency_ms"] = int((time.time() - db_start) * 1000)  # type: ignore

    # Broker check (короткий тикер)
    brk_start = time.time()
    brk_res = {"status": "ok", "latency_ms": 0}
    try:
        # символ из настроек, но short-timeout (если поддерживается)
        _ = app.state.broker.fetch_ticker(cfg.SYMBOL)  # type: ignore
    except Exception as e:
        brk_res["status"] = f"error:{type(e).__name__}"  # type: ignore
        brk_res["detail"] = str(e)[:200]  # type: ignore
    finally:
        brk_res["latency_ms"] = int((time.time() - brk_start) * 1000)  # type: ignore

    # Time drift
    time_res: Dict[str, Any] = {"status": "ok", "drift_ms": 0, "limit_ms": cfg.TIME_DRIFT_LIMIT_MS}
    try:
        if measure_time_drift:
            sources = cfg.TIME_DRIFT_URLS or DEFAULT_TIME_SOURCES
            drift_ms = asyncio.get_event_loop().run_until_complete(
                measure_time_drift(app.state.http, sources)
            )
            time_res["drift_ms"] = int(drift_ms)
            # обязательный gauge
            metrics.set_gauge("time_drift_ms", float(drift_ms))
            if int(drift_ms) > int(cfg.TIME_DRIFT_LIMIT_MS):
                time_res["status"] = "drift_exceeded"
        else:
            time_res["status"] = "unknown"
    except Exception as e:
        time_res["status"] = f"error:{type(e).__name__}"
        time_res["detail"] = str(e)[:200]

    components = {
        "mode": cfg.MODE,
        "db": db_res,
        "broker": brk_res,
        "time": time_res,
    }
    rollup = _health_rollup(components)
    payload = dict(rollup, components=components)
    return JSONResponse(payload)


@app.get("/metrics")
def metrics_export() -> Response:
    return PlainTextResponse(metrics.export(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/config")
def get_config() -> Response:
    cfg: Settings = app.state.cfg
    try:
        profile = cfg.get_profile_dict()  # optional helper
    except Exception:
        profile = {}

    out = {
        "mode": cfg.MODE,
        "paper": cfg.PAPER_MODE,
        "safe_mode": getattr(cfg, "SAFE_MODE", False),
        "symbol": cfg.SYMBOL,
        "timeframe": cfg.TIMEFRAME,
        "rate_limits": {
            "evaluate_per_min": getattr(cfg, "RL_EVALUATE_PER_MIN", 60),
            "orders_per_min": getattr(cfg, "RL_ORDERS_PER_MIN", 10),
        },
        "time_drift_limit_ms": cfg.TIME_DRIFT_LIMIT_MS,
        "metrics_refresh_sec": getattr(cfg, "METRICS_REFRESH_SEC", 30),
        "profile": profile,
    }
    return JSONResponse(out)


@app.post("/tick")
async def tick(request: Request) -> Response:
    """Лёгкий хук для ручного цикла оценки (без исполнения ордера)."""
    cfg: Settings = app.state.cfg
    body: Dict[str, Any] = {}
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
    except Exception:
        body = {}

    symbol = (body.get("symbol") or cfg.SYMBOL)
    timeframe = (body.get("timeframe") or cfg.TIMEFRAME)
    limit = int(body.get("limit") or 300)

    try:
        decision = uc_evaluate(cfg, app.state.broker, symbol=symbol, timeframe=timeframe, limit=limit)
        return JSONResponse({"status": "evaluated", "symbol": symbol, "timeframe": timeframe, "decision": decision})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {str(e)[:200]}"})


@app.get("/bus/metrics")
async def bus_metrics() -> Response:
    bus: AsyncBus = app.state.bus
    stats = bus.get_stats()
    return JSONResponse(stats)
