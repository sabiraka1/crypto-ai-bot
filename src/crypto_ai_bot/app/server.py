from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Body
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

@app.get("/positions")
def get_positions_snapshot():
    try:
        snap = positions_manager.get_snapshot()
        return JSONResponse({"status": "ok", "snapshot": snap})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"positions_snapshot_failed:{type(e).__name__}: {e}"})

def _ensure_trading_enabled():
    if not getattr(CFG, "ENABLE_TRADING", False):
        raise HTTPException(status_code=403, detail="Trading is disabled by configuration")

def _build_manual_decision(action: str, size: str, symbol: str | None = None, timeframe: str | None = None) -> Dict[str, Any]:
    sym = normalize_symbol(symbol or getattr(CFG, "SYMBOL", "BTC/USDT"))
    tf = normalize_timeframe(timeframe or getattr(CFG, "TIMEFRAME", "1h"))
    try:
        # на клиентском уровне передаем число как строку
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
    res = place_order(CFG, BOT.broker, decision=decision, idem_repo=IDEM, trades_repo=TRD_REPO, audit_repo=AUDIT_REPO)
    return JSONResponse(res)

@app.post("/orders/sell")
def orders_sell(payload: Dict[str, Any] = Body(...)):
    _ensure_trading_enabled()
    size = str(payload.get("size", getattr(CFG, "DEFAULT_ORDER_SIZE", "0.01")))
    symbol = payload.get("symbol")
    timeframe = payload.get("timeframe")

    decision = _build_manual_decision("sell", size=size, symbol=symbol, timeframe=timeframe)
    res = place_order(CFG, BOT.broker, decision=decision, idem_repo=IDEM, trades_repo=TRD_REPO, audit_repo=AUDIT_REPO)
    return JSONResponse(res)

@app.post("/tick")
async def tick():
    try:
        dec = BOT.evaluate()
        return JSONResponse({"status": "evaluated", "symbol": dec.get("symbol", getattr(CFG, "SYMBOL", "BTC/USDT")), "timeframe": dec.get("timeframe", getattr(CFG, "TIMEFRAME", "1h")), "decision": dec})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"})
