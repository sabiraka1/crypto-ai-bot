from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.logging import init as init_logging
from crypto_ai_bot.utils.time_sync import measure_time_drift

from crypto_ai_bot.app.adapters.telegram import handle_update as tg_handle_update

from crypto_ai_bot.core.storage.sqlite_adapter import (
    connect as db_connect, in_txn, get_db_stats, perform_maintenance
)
from crypto_ai_bot.core.storage.migrations.runner import apply_all as apply_migrations
from crypto_ai_bot.core.storage.repositories.trades import TradeRepository
from crypto_ai_bot.core.storage.repositories.positions import PositionRepository
from crypto_ai_bot.core.storage.repositories.snapshots import SnapshotRepository
from crypto_ai_bot.core.storage.repositories.audit import AuditRepository
from crypto_ai_bot.core.storage.repositories.idempotency import IdempotencyRepository

from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.core.positions.tracker import build_context

app = FastAPI(title="Crypto AI Bot")

cfg = Settings.build()
init_logging()
metrics.inc("app_start_total", {"mode": cfg.MODE})

broker = create_broker(cfg)
metrics.inc("broker_created_total", {"mode": cfg.MODE})

_db_conn = None
_repos: Dict[str, Any] = {}
_maint_task: Optional[asyncio.Task] = None

def _ensure_db_and_repos() -> Dict[str, Any]:
    global _db_conn, _repos
    if _repos:
        return _repos
    _db_conn = db_connect(cfg.DB_PATH)
    apply_migrations(_db_conn)
    _repos = {
        "positions_repo": PositionRepository(_db_conn, cfg),
        "trades_repo":    TradeRepository(_db_conn, cfg),
        "snapshots_repo": SnapshotRepository(_db_conn, cfg),
        "audit_repo":     AuditRepository(_db_conn, cfg),
        "idempotency_repo": IdempotencyRepository(_db_conn),
    }
    metrics.inc("db_connected_total", {})
    return _repos

@app.on_event("startup")
async def _startup_event() -> None:
    global _maint_task
    _ = _ensure_db_and_repos()
    async def _maint_loop():
        interval = int(getattr(cfg, "DB_MAINTENANCE_INTERVAL_SEC", 900))
        while True:
            try:
                perform_maintenance(_db_conn, cfg)
            except Exception:
                pass
            await asyncio.sleep(max(5, interval))
    _maint_task = asyncio.create_task(_maint_loop())

@app.on_event("shutdown")
async def _shutdown_event() -> None:
    global _db_conn, _repos, _maint_task
    try:
        if _maint_task:
            _maint_task.cancel()
    except Exception:
        pass
    try:
        if _db_conn is not None:
            _db_conn.close()
    except Exception:
        pass
    _maint_task = None
    _db_conn = None
    _repos = {}

@app.get("/health")
async def health() -> Dict[str, Any]:
    components: Dict[str, Any] = {"mode": cfg.MODE}

    try:
        _ = _ensure_db_and_repos()
        with in_txn(_db_conn):
            pass
        components["db"] = {"status": "ok", "latency_ms": 0}
    except Exception as e:
        components["db"] = {"status": f"error:{type(e).__name__}", "detail": str(e), "latency_ms": 0}

    try:
        _ = broker.fetch_ticker(cfg.SYMBOL)
        components["broker"] = {"status": "ok", "latency_ms": 0}
    except Exception as e:
        components["broker"] = {"status": f"error:{type(e).__name__}", "detail": str(e), "latency_ms": 0}

    try:
        drift_ms = int(measure_time_drift())
    except Exception:
        drift_ms = 0
    components["time"] = {"status": "ok", "drift_ms": drift_ms, "limit_ms": int(getattr(cfg, "TIME_DRIFT_MAX_MS", 1500))}

    status = "healthy"
    degradation = "none"
    if components.get("db", {}).get("status") != "ok" or components.get("broker", {}).get("status") != "ok":
        status, degradation = "degraded", "major"
    elif drift_ms > int(getattr(cfg, "TIME_DRIFT_MAX_MS", 1500)):
        status, degradation = "degraded", "minor"

    return {"status": status, "degradation_level": degradation, "components": components}

@app.get("/metrics", response_class=PlainTextResponse)
async def get_metrics() -> str:
    return metrics.export()

def _limits_from_cfg(cfg) -> Dict[str, Any]:
    return {
        "spread_pct": float(getattr(cfg, "MAX_SPREAD_PCT", 0.25)),
        "drawdown_pct": float(getattr(cfg, "MAX_DRAWDOWN_PCT", 5.0)),
        "seq_losses": int(getattr(cfg, "MAX_SEQ_LOSSES", 3)),
        "exposure_pct": getattr(cfg, "MAX_EXPOSURE_PCT", None),
        "exposure_usd": getattr(cfg, "MAX_EXPOSURE_USD", None),
        "time_drift_ms": int(getattr(cfg, "TIME_DRIFT_MAX_MS", 1500)),
        "hours": [int(getattr(cfg, "TRADING_START_HOUR", 0)), int(getattr(cfg, "TRADING_END_HOUR", 24))],
        "thresholds": {"buy": float(getattr(cfg, "THRESHOLD_BUY", 0.6)), "sell": float(getattr(cfg, "THRESHOLD_SELL", 0.4))},
        "weights": {"rule": float(getattr(cfg, "SCORE_RULE_WEIGHT", 0.5)), "ai": float(getattr(cfg, "SCORE_AI_WEIGHT", 0.5))},
    }

@app.get("/status")
async def http_status(symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: int = 300) -> Dict[str, Any]:
    try:
        repos = _ensure_db_and_repos()
        sym = symbol or cfg.SYMBOL
        tf = timeframe or cfg.TIMEFRAME

        summary = build_context(cfg, broker, positions_repo=repos.get("positions_repo"), trades_repo=repos.get("trades_repo"))
        risk_ok, risk_reason = risk_manager.check(summary, cfg)

        dec = evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit, **repos)

        return {
            "status": "ok",
            "symbol": sym,
            "timeframe": tf,
            "summary": summary,
            "risk": {"ok": bool(risk_ok), "reason": risk_reason},
            "limits": _limits_from_cfg(cfg),
            "decision": {"action": dec.get("action"), "score": dec.get("score")},
        }
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}

@app.get("/debug/db_stats")
async def db_stats() -> Dict[str, Any]:
    _ = _ensure_db_and_repos()
    return get_db_stats(_db_conn, cfg.DB_PATH)

@app.post("/execute")
async def http_execute(symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: int = 300) -> Dict[str, Any]:
    try:
        repos = _ensure_db_and_repos()
        res = eval_and_execute(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit, **repos)
        return {"status": "ok", **res}
    except Exception as e:
        return {"status": "error", "error": f"execute_failed: {type(e).__name__}: {e}"}

@app.post("/telegram")
async def telegram_webhook(request: Request) -> Dict[str, Any]:
    secret_hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if getattr(cfg, "TELEGRAM_SECRET_TOKEN", "") and secret_hdr != cfg.TELEGRAM_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")
    repos = _ensure_db_and_repos()
    return tg_handle_update(update, cfg, broker, **repos)

@app.post("/tick")
async def tick(symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: int = 300) -> Dict[str, Any]:
    try:
        repos = _ensure_db_and_repos()
        dec = evaluate(cfg, broker, symbol=symbol or cfg.SYMBOL, timeframe=timeframe or cfg.TIMEFRAME, limit=limit, **repos)
        return {"status": "evaluated", "symbol": dec.get("symbol"), "timeframe": dec.get("timeframe"), "decision": dec}
    except Exception as e:
        return {"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"}
