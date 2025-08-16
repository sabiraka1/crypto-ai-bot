from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Body, Query
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
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.events import AsyncBus
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.utils.time_sync import measure_time_drift

app = FastAPI(title="crypto-ai-bot")

CFG = Settings.build()
DB_PATH = getattr(CFG, "DB_PATH", "data/bot.sqlite")
CON = connect(DB_PATH)

# repositories
IDEM = SqliteIdempotencyRepository(CON)
POS_REPO = SqlitePositionRepository(CON)
TRD_REPO = SqliteTradeRepository(CON)
AUDIT_REPO = SqliteAuditRepository(CON)

# positions layer wires
positions_manager.configure_repositories(positions_repo=POS_REPO, trades_repo=TRD_REPO, audit_repo=AUDIT_REPO)

# event bus with strategies (optional via settings)
BUS = AsyncBus(
    strategies=getattr(CFG, "BUS_STRATEGIES", {"OrderSubmittedEvent": "drop_oldest", "ErrorEvent": "keep_latest"}),
    queue_sizes=getattr(CFG, "BUS_QUEUE_SIZES", {"OrderSubmittedEvent": 2000, "ErrorEvent": 500}),
    dlq_max=int(getattr(CFG, "BUS_DLQ_MAX", 500)),
)

# bot
BOT = TradingBot(CFG, idem_repo=IDEM, bus=BUS)

HTTP = get_http_client()

# --- simple consumers (example) ---
async def order_submitted_consumer(event: Dict[str, Any]) -> None:
    metrics.inc("bus_order_submitted_total")
    # минимальная обработка; всё важное уже записано audit_repo/trades_repo

async def error_event_consumer(event: Dict[str, Any]) -> None:
    metrics.inc("bus_error_total", {"scope": str(event.get("scope","unknown"))})

BUS.subscribe("OrderSubmittedEvent", order_submitted_consumer)
BUS.subscribe("ErrorEvent", error_event_consumer)

_consumer_tasks: list[asyncio.Task] = []

@app.on_event("startup")
async def _on_start() -> None:
    metrics.inc("app_start_total", {"mode": getattr(CFG, "MODE", "paper")})
    # запустим consumers
    for et in ("OrderSubmittedEvent", "ErrorEvent"):
        _consumer_tasks.append(asyncio.create_task(BUS.run_consumer(et)))

@app.on_event("shutdown")
async def _on_stop() -> None:
    # аккуратная остановка consumers
    for t in _consumer_tasks:
        t.cancel()
    await asyncio.gather(*_consumer_tasks, return_exceptions=True)

@app.get("/metrics")
def metrics_endpoint():
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

    # Time drift via HTTP (safe fallback on error)
    try:
        drift = measure_time_drift(HTTP, timeout=float(getattr(CFG, "HEALTH_TIME_TIMEOUT_S", 2.0)))
        drift_ms = int(drift.get("drift_ms", 0) or 0)
        setattr(CFG, "TIME_DRIFT_MS", drift_ms)
        time_status = {"status": "ok" if drift.get("ok") else "error", "drift_ms": drift_ms, "latency_ms": int(drift.get("latency_ms", -1))}
    except Exception as e:
        time_status = {"status": f"error:{type(e).__name__}", "drift_ms": None, "latency_ms": None}

    # Migrations health (optional, keep safe if not available)
    try:
        from crypto_ai_bot.core.storage.migrations.runner import pending_migrations_count
        pend = pending_migrations_count(CON)
        mig_status = {"status": "ok", "pending": 0}
        if pend > 0:
            mig_status = {"status": "pending", "pending": int(pend)}
    except Exception:
        mig_status = {"status": "unknown", "pending": None}

    statuses = [db_status.get("status"), br_status.get("status"), time_status.get("status")]
    level = "none"
    overall = "healthy"
    if any(isinstance(s, str) and s.startswith("error") for s in statuses):
        overall, level = "degraded", "major"
    return JSONResponse({
        "status": overall,
        "degradation_level": level,
        "components": {
            "mode": getattr(CFG, "MODE", "paper"),
            "db": db_status,
            "broker": br_status,
            "time": time_status,
            "db_stats": {"open_fds": None},
        }
    })

def _ensure_trading_enabled():
    if not getattr(CFG, "ENABLE_TRADING", False):
        raise HTTPException(status_code=403, detail="Trading is disabled by configuration")

def _build_manual_decision(action: str, size: str, symbol: str | None = None, timeframe: str | None = None) -> Dict[str, Any]:
    sym = normalize_symbol(symbol or getattr(CFG, "SYMBOL", "BTC/USDT"))
    tf = normalize_timeframe(timeframe or getattr(CFG, "TIMEFRAME", "1h"))
    try:
        sz = str(size)
    except Exception:
        sz = "0"
    return {
        "id": f"manual-{action}-{sym}-{tf}",
        "action": action,
        "size": sz,
        "symbol": sym,
        "timeframe": tf,
        "explain": {
            "context": {"id": f"manual-{action}", "source": "manual"},
            "signals": {},
            "blocks": {},
            "weights": {
                "rule": float(getattr(CFG, "SCORE_RULE_WEIGHT", 0.5)),
                "ai": float(getattr(CFG, "SCORE_AI_WEIGHT", 0.5)),
            },
            "thresholds": {
                "buy": float(getattr(CFG, "THRESHOLD_BUY", 0.55)),
                "sell": float(getattr(CFG, "THRESHOLD_SELL", 0.45)),
            },
        },
    }

@app.post("/orders/buy")
def orders_buy(payload: Dict[str, Any] = Body(...)):
    _ensure_trading_enabled()
    size = str(payload.get("size", getattr(CFG, "DEFAULT_ORDER_SIZE", "0.01")))
    symbol = payload.get("symbol")
    timeframe = payload.get("timeframe")

    decision = _build_manual_decision("buy", size=size, symbol=symbol, timeframe=timeframe)
    res = place_order(CFG, BOT.broker, decision=decision, idem_repo=IDEM, trades_repo=TRD_REPO, audit_repo=AUDIT_REPO, bus=BUS)
    return JSONResponse(res)

@app.post("/orders/sell")
def orders_sell(payload: Dict[str, Any] = Body(...)):
    _ensure_trading_enabled()
    size = str(payload.get("size", getattr(CFG, "DEFAULT_ORDER_SIZE", "0.01")))
    symbol = payload.get("symbol")
    timeframe = payload.get("timeframe")

    decision = _build_manual_decision("sell", size=size, symbol=symbol, timeframe=timeframe)
    res = place_order(CFG, BOT.broker, decision=decision, idem_repo=IDEM, trades_repo=TRD_REPO, audit_repo=AUDIT_REPO, bus=BUS)
    return JSONResponse(res)

@app.get("/why")
def get_why():
    try:
        dec = BOT.evaluate()
        return JSONResponse({"status": "ok", "decision": dec, "explain": dec.get("explain")})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"why_failed: {type(e).__name__}: {e}"})

@app.post("/tick")
async def tick():
    try:
        dec = BOT.evaluate()
        return JSONResponse({"status": "evaluated", "symbol": dec.get("symbol", getattr(CFG, "SYMBOL", "BTC/USDT")), "timeframe": dec.get("timeframe", getattr(CFG, "TIMEFRAME", "1h")), "decision": dec})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"})
