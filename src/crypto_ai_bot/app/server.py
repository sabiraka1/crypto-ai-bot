from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.bot import TradingBot
from crypto_ai_bot.core.storage.sqlite_adapter import connect, get_db_stats, perform_maintenance
from crypto_ai_bot.core.storage.migrations.runner import pending_migrations_count
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository
from crypto_ai_bot.core.positions import manager as positions_manager
from crypto_ai_bot.utils import metrics

app = FastAPI(title="crypto-ai-bot")

CFG = Settings.build()
DB_PATH = getattr(CFG, "DB_PATH", "data/bot.sqlite")
CON = connect(DB_PATH)

# repositories
IDEM = SqliteIdempotencyRepository(CON)
POS_REPO = SqlitePositionRepository(CON)
TRD_REPO = SqliteTradeRepository(CON)
AUDIT_REPO = SqliteAuditRepository(CON)

# wire repos into positions manager (so place_order/open() writes to DB)
positions_manager.configure_repositories(positions_repo=POS_REPO, trades_repo=TRD_REPO, audit_repo=AUDIT_REPO)

# bot
BOT = TradingBot(CFG, idem_repo=IDEM)

@app.on_event("startup")
async def _on_start() -> None:
    metrics.inc("app_start_total", {"mode": getattr(CFG, "MODE", "paper")})

@app.get("/metrics")
def metrics_endpoint():
    try:
        cb = getattr(BOT.broker, "cb", None)
        if cb is not None and hasattr(cb, "get_stats"):
            st = cb.get_stats()
            open_count = 0
            fails_sum = 0
            err_count = 0
            for key, info in st.items():
                if isinstance(info, dict):
                    if info.get("state") == "open":
                        open_count += 1
                    fails_sum += int(info.get("fails", 0) or 0)
                    if info.get("last_error"):
                        err_count += 1
            metrics.observe("circuit_open_gauge", float(open_count))
            metrics.observe("circuit_fails_gauge", float(fails_sum))
            metrics.observe("circuit_keys_with_last_error", float(err_count))
    except Exception:
        pass
    return PlainTextResponse(metrics.export(), media_type="text/plain; version=0.0.4; charset=utf-8")

@app.get("/health")
def health():
    # DB
    try:
        t0 = time.perf_counter()
        CON.execute("SELECT 1;").fetchone()
        db_lat = int((time.perf_counter() - t0) * 1000)
        db_status = {"status": "ok", "latency_ms": db_lat}
    except Exception as e:
        db_status = {"status": f"error:{type(e).__name__}"}

    # Broker (ticker)
    try:
        t0 = time.perf_counter()
        BOT.broker.fetch_ticker(getattr(CFG, "SYMBOL", "BTC/USDT"))
        br_lat = int((time.perf_counter() - t0) * 1000)
        br_status = {"status": "ok", "latency_ms": br_lat}
    except Exception as e:
        br_status = {"status": f"error:{type(e).__name__}"}

    # Time drift (stub 0 for now)
    drift_ms = 0
    time_status = {"status": "ok", "drift_ms": drift_ms, "limit_ms": int(getattr(CFG, "TIME_DRIFT_LIMIT_MS", 1000))}

    # Migrations health
    try:
        pend = pending_migrations_count(CON)
        mig_status = {"status": "ok", "pending": 0}
        if pend > 0:
            mig_status = {"status": "pending", "pending": int(pend)}
    except Exception as e:
        mig_status = {"status": f"error:{type(e).__name__}", "pending": None}

    # Maintenance
    try:
        perform_maintenance(CON, CFG)
    except Exception:
        pass

    statuses = [db_status.get("status"), br_status.get("status"), time_status.get("status"), mig_status.get("status")]
    level = "none"
    overall = "healthy"
    if any(isinstance(s, str) and s.startswith("error") for s in statuses):
        overall, level = "degraded", "major"
    elif mig_status.get("status") == "pending":
        overall, level = "degraded", "minor"

    return JSONResponse({
        "status": overall,
        "degradation_level": level,
        "components": {
            "mode": getattr(CFG, "MODE", "paper"),
            "db": db_status,
            "broker": br_status,
            "time": time_status,
            "migrations": mig_status,
            "db_stats": get_db_stats(CON),
        }
    })

@app.post("/tick")
async def tick():
    try:
        dec = BOT.evaluate()
        return JSONResponse({"status": "evaluated", "symbol": dec.get("symbol", getattr(CFG, "SYMBOL", "BTC/USDT")), "timeframe": dec.get("timeframe", getattr(CFG, "TIMEFRAME", "1h")), "decision": dec})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"})
