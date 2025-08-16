from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.logging import init as init_logging
from crypto_ai_bot.utils.time_sync import measure_time_drift

# Telegram adapter
from crypto_ai_bot.app.adapters.telegram import handle_update as tg_handle_update

# Storage (SQLite) wiring
from crypto_ai_bot.core.storage.sqlite_adapter import connect as db_connect, in_txn
from crypto_ai_bot.core.storage.migrations.runner import apply_all as apply_migrations
from crypto_ai_bot.core.storage.repositories.trades import TradeRepository
from crypto_ai_bot.core.storage.repositories.positions import PositionRepository
from crypto_ai_bot.core.storage.repositories.snapshots import SnapshotRepository
from crypto_ai_bot.core.storage.repositories.audit import AuditRepository

# (new) fast summary uses tracker (repo-aware)
from crypto_ai_bot.core.positions.tracker import build_context

app = FastAPI(title="Crypto AI Bot")

cfg = Settings.build()
init_logging()
metrics.inc("app_start_total", {"mode": cfg.MODE})

# Broker
broker = create_broker(cfg)
metrics.inc("broker_created_total", {"mode": cfg.MODE})

# DB + repositories (cached singletons)
_db_conn = None
_repos: Dict[str, Any] = {}

def _ensure_db_and_repos() -> Dict[str, Any]:
    global _db_conn, _repos
    if _repos:
        return _repos
    _db_conn = db_connect(cfg.DB_PATH)
    apply_migrations(_db_conn)
    _repos = {
        "positions_repo": PositionRepository(_db_conn),
        "trades_repo":    TradeRepository(_db_conn),
        "snapshots_repo": SnapshotRepository(_db_conn),
        "audit_repo":     AuditRepository(_db_conn),
    }
    metrics.inc("db_connected_total", {})
    return _repos

@app.on_event("shutdown")
async def _shutdown_event() -> None:
    global _db_conn, _repos
    try:
        if _db_conn is not None:
            _db_conn.close()
    except Exception:
        pass
    _db_conn = None
    _repos = {}

# ----------------------------------------------------------------------------
# Health & metrics
# ----------------------------------------------------------------------------

@app.get("/health")
async def health() -> Dict[str, Any]:
    components: Dict[str, Any] = {"mode": cfg.MODE}

    # DB
    try:
        _ = _ensure_db_and_repos()
        with in_txn(_db_conn):
            pass
        components["db"] = {"status": "ok", "latency_ms": 0}
    except Exception as e:
        components["db"] = {"status": f"error:{type(e).__name__}", "detail": str(e), "latency_ms": 0}

    # Broker ping
    try:
        _ = broker.fetch_ticker(cfg.SYMBOL)
        components["broker"] = {"status": "ok", "latency_ms": 0}
    except Exception as e:
        components["broker"] = {"status": f"error:{type(e).__name__}", "detail": str(e), "latency_ms": 0}

    # Time drift
    try:
        drift_ms = int(measure_time_drift())
    except Exception:
        drift_ms = 0
    components["time"] = {"status": "ok", "drift_ms": drift_ms, "limit_ms": int(cfg.TIME_DRIFT_MAX_MS)}

    status = "healthy"
    degradation = "none"
    if components.get("db", {}).get("status") != "ok" or components.get("broker", {}).get("status") != "ok":
        status, degradation = "degraded", "major"
    elif drift_ms > int(cfg.TIME_DRIFT_MAX_MS):
        status, degradation = "degraded", "minor"

    return {"status": status, "degradation_level": degradation, "components": components}

@app.get("/metrics", response_class=PlainTextResponse)
async def get_metrics() -> str:
    return metrics.export()

# ----------------------------------------------------------------------------
# Debug/status endpoints
# ----------------------------------------------------------------------------

@app.get("/status")
async def http_status(symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: int = 300) -> Dict[str, Any]:
    """
    Лёгкий status: decision + fast summary (exposure/dd/seq_losses/price/spread) без лишних подробностей.
    """
    try:
        repos = _ensure_db_and_repos()
        sym = symbol or cfg.SYMBOL
        tf = timeframe or cfg.TIMEFRAME

        # лёгкий контекст для быстрого ответа (не требует тяжёлых индикаторов)
        summary = build_context(cfg, broker, positions_repo=repos.get("positions_repo"), trades_repo=repos.get("trades_repo"))

        # полное решение (использует индикаторы) — оставляем как было
        dec = evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit, **repos)

        return {
            "status": "ok",
            "symbol": sym,
            "timeframe": tf,
            "summary": summary,
            "decision": {
                "action": dec.get("action"),
                "score": dec.get("score"),
            },
        }
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}

@app.get("/debug/why")
async def http_why(symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: int = 300) -> Dict[str, Any]:
    try:
        repos = _ensure_db_and_repos()
        dec = evaluate(cfg, broker, symbol=symbol or cfg.SYMBOL, timeframe=timeframe or cfg.TIMEFRAME, limit=limit, **repos)
        return {"status": "ok", "symbol": dec.get("symbol"), "timeframe": dec.get("timeframe"), "action": dec.get("action"), "score": dec.get("score"), "explain": dec.get("explain")}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}

@app.get("/debug/audit")
async def http_audit(type: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    try:
        repos = _ensure_db_and_repos()
        audit = repos.get("audit_repo")
        if audit is None:
            return {"status": "error", "error": "audit_repo_not_configured"}
        items = audit.list_by_type(type, limit) if type else audit.list_recent(limit)
        return {"status": "ok", "items": items}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}

# ----------------------------------------------------------------------------
# Telegram webhook
# ----------------------------------------------------------------------------

@app.post("/telegram")
async def telegram_webhook(request: Request) -> Dict[str, Any]:
    secret_hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if cfg.TELEGRAM_SECRET_TOKEN and secret_hdr != cfg.TELEGRAM_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")
    repos = _ensure_db_and_repos()
    resp = tg_handle_update(update, cfg, broker, **repos)
    return resp

# ----------------------------------------------------------------------------
# Optional: tick endpoint
# ----------------------------------------------------------------------------

@app.post("/tick")
async def tick(symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: int = 300) -> Dict[str, Any]:
    try:
        repos = _ensure_db_and_repos()
        dec = evaluate(cfg, broker, symbol=symbol or cfg.SYMBOL, timeframe=timeframe or cfg.TIMEFRAME, limit=limit, **repos)
        return {"status": "evaluated", "symbol": dec.get("symbol"), "timeframe": dec.get("timeframe"), "decision": dec}
    except Exception as e:
        return {"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"}
