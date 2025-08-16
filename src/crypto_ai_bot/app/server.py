# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers import create_broker
from crypto_ai_bot.core.storage import connect, SqliteUnitOfWork
from crypto_ai_bot.core.storage.repositories import (
    SqliteTradeRepository,
    SqlitePositionRepository,
    SqliteSnapshotRepository,
    SqliteAuditRepository,
    SqliteIdempotencyRepository,
)
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute
from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.utils import metrics, time_sync as ts
from crypto_ai_bot.core.orchestrator import Orchestrator

try:
    from crypto_ai_bot.app.adapters.telegram import handle_update as tg_handle_update
    _HAS_TG = True
except Exception:
    tg_handle_update = None  # type: ignore
    _HAS_TG = False

cfg = Settings.build()
db_path = Path(getattr(cfg, "DB_PATH", "data/bot.db"))
db_path.parent.mkdir(parents=True, exist_ok=True)
con = connect(str(db_path))
uow = SqliteUnitOfWork(con)
repos: Dict[str, Any] = {
    "trades": SqliteTradeRepository(con),
    "positions": SqlitePositionRepository(con),
    "snapshots": SqliteSnapshotRepository(con),
    "audit": SqliteAuditRepository(con),
    "idempotency": SqliteIdempotencyRepository(con),
    "uow": uow,
}
broker = create_broker(cfg)
http = get_http_client()
app = FastAPI(title="Crypto AI Bot", version=getattr(cfg, "APP_VERSION", "0.1.0"))

orch = Orchestrator(cfg=cfg, broker=broker, repos=repos, http=http)

def _component_health() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "mode": cfg.MODE,
        "db": {"status": "unknown", "latency_ms": None},
        "broker": {"status": "unknown", "latency_ms": None},
        "time": {"status": "unknown", "drift_ms": None, "source": None},
    }
    # DB
    t0 = time.perf_counter()
    try:
        con.execute("SELECT 1;")
        out["db"]["status"] = "ok"
    except Exception as e:
        out["db"]["status"] = f"error:{type(e).__name__}"
    out["db"]["latency_ms"] = int((time.perf_counter() - t0) * 1000)

    # Broker
    t0 = time.perf_counter()
    try:
        _ = broker.fetch_ticker(cfg.SYMBOL)
        out["broker"]["status"] = "ok"
    except Exception as e:
        out["broker"]["status"] = f"error:{type(e).__name__}"
    out["broker"]["latency_ms"] = int((time.perf_counter() - t0) * 1000)

    # Time drift (используем кеш; если устарел — Orchestrator обновит)
    drift = ts.get_cached_drift_ms(None)
    out["time"]["drift_ms"] = drift
    out["time"]["source"] = "worldtimeapi"
    lim = int(getattr(cfg, "TIME_DRIFT_MAX_MS", 1500))
    out["time"]["status"] = "ok" if abs(drift or 0) <= lim else "error:drift"

    return out

def _overall_status(comp: Dict[str, Any]) -> tuple[str, str]:
    errs = []
    lat = []
    # собираем статусы
    for k in ("db", "broker", "time"):
        st = comp.get(k, {}).get("status")
        if isinstance(st, str) and st.startswith("error"):
            errs.append(k)
    # деградация по латентности (порог можно вынести в Settings)
    db_ms = comp["db"]["latency_ms"] or 0
    br_ms = comp["broker"]["latency_ms"] or 0
    lat = max(db_ms, br_ms)

    if errs:
        status = "degraded"
        level = "major" if "db" in errs or "broker" in errs else "minor"
    else:
        status = "healthy"
        level = "none"

    # если нет ошибок, но очень медленно — считаем degraded/minor
    if not errs and lat > int(getattr(cfg, "HEALTH_LATENCY_WARN_MS", 1500)):
        status = "degraded"
        level = "minor"

    return status, level

@app.get("/health")
def health() -> JSONResponse:
    comp = _component_health()
    status, level = _overall_status(comp)
    metrics.observe("health_check_duration_seconds", (comp["db"]["latency_ms"] or 0) / 1000.0, {"status": status})
    payload = {
        "status": status,
        "degradation_level": level,
        "components": comp,
        "symbol": cfg.SYMBOL,
        "timeframe": cfg.TIMEFRAME,
        "mode": cfg.MODE,
        "version": getattr(cfg, "APP_VERSION", "0.1.0"),
    }
    return JSONResponse(payload)

@app.get("/metrics")
def metrics_export() -> Response:
    return PlainTextResponse(metrics.export(), media_type="text/plain; version=0.0.4; charset=utf-8")

@app.post("/telegram")
async def telegram_webhook(request: Request) -> JSONResponse:
    if not _HAS_TG or tg_handle_update is None:
        raise HTTPException(status_code=501, detail="telegram adapter not installed")
    secret = getattr(cfg, "TELEGRAM_WEBHOOK_SECRET", None)
    if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        raise HTTPException(status_code=403, detail="forbidden")
    raw = await request.body()
    try:
        update = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        update = {}
    try:
        result = await tg_handle_update(update, cfg, broker, http)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    return JSONResponse(result or {"ok": True})

@app.post("/tick")
def tick() -> JSONResponse:
    try:
        res = uc_eval_and_execute(
            cfg,
            broker,
            symbol=cfg.SYMBOL,
            timeframe=cfg.TIMEFRAME,
            limit=int(getattr(cfg, "FEATURE_LIMIT", 300)),
            repos=repos,
        )
        return JSONResponse({"ok": True, "result": res})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.on_event("startup")
async def on_startup() -> None:
    metrics.inc("app_start_total", {"mode": cfg.MODE})
    await orch.start()

@app.on_event("shutdown")
async def on_shutdown() -> None:
    metrics.inc("app_stop_total", {"mode": cfg.MODE})
    try:
        await orch.stop()
    except Exception:
        pass
    try:
        con.close()
    except Exception:
        pass
