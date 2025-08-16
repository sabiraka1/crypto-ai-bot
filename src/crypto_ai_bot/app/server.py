from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

from fastapi import FastAPI, Request
from pydantic import BaseModel

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.utils.metrics import export as metrics_export, observe
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time_sync import measure_time_drift
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.migrations.runner import apply_all

log = get_logger(__name__)
app = FastAPI(title="crypto-ai-bot")


class TickIn(BaseModel):
    symbol: str | None = None
    timeframe: str | None = None
    limit: int | None = None


@app.on_event("startup")
async def _startup() -> None:
    cfg = Settings.build()
    # миграции (если нужно)
    con = connect(cfg.DB_PATH)
    apply_all(con)
    # прогрев брокера
    app.state.cfg = cfg
    app.state.broker = create_broker(cfg)
    log.info("app_started", extra={"mode": cfg.MODE})
    observe("app_start_total", 1.0, {"mode": cfg.MODE})


@app.get("/metrics")
async def metrics() -> Any:
    return metrics_export()


@app.get("/health")
async def health() -> Dict[str, Any]:
    cfg = app.state.cfg

    # DB health
    db_t0 = time.perf_counter()
    try:
        con = connect(cfg.DB_PATH)
        con.execute("SELECT 1").fetchone()
        db = {"status": "ok", "latency_ms": int((time.perf_counter() - db_t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        db = {"status": f"error:{type(exc).__name__}"}

    # Broker health (fetch_ticker с коротким таймаутом, если поддерживается)
    br_t0 = time.perf_counter()
    try:
        _ = app.state.broker.fetch_ticker(cfg.SYMBOL)
        broker = {"status": "ok", "latency_ms": int((time.perf_counter() - br_t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        broker = {"status": f"error:{type(exc).__name__}", "latency_ms": int((time.perf_counter() - br_t0) * 1000)}

    # Time drift
    drift, _ = measure_time_drift(urls=cfg.TIME_DRIFT_URLS or None, timeout=2.5)
    timec = {"status": "ok" if abs(drift) <= cfg.TIME_DRIFT_LIMIT_MS else "error:drift", "drift_ms": drift, "limit_ms": cfg.TIME_DRIFT_LIMIT_MS}

    # Матрица статусов
    if db["status"] != "ok" or timec["status"] != "ok":
        status = "unhealthy"
        degradation = "critical"
    elif broker["status"] != "ok":
        status = "degraded"
        degradation = "no_trading"
    else:
        status = "healthy"
        degradation = "none"

    return {
        "status": status,
        "degradation_level": degradation,
        "components": {
            "mode": cfg.MODE,
            "db": db,
            "broker": broker,
            "time": timec,
        },
    }


@app.post("/tick")
async def tick(inp: TickIn) -> Dict[str, Any]:
    # заглушка: просто живой «пульс», чтобы проверить, что цикл не падает
    try:
        _ = inp.dict()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
