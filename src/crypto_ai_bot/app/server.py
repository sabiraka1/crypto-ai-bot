# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Header, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.logging import init as init_logging
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils.http_client import get_http_client
# time drift (safe import)
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift
except Exception:  # pragma: no cover
    measure_time_drift = None  # type: ignore

from crypto_ai_bot.app.adapters import telegram as tg_adapter

from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe

from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute

from crypto_ai_bot.core.storage.sqlite_adapter import connect, snapshot_metrics as sqlite_snapshot
from crypto_ai_bot.core.storage.uow import SqliteUnitOfWork
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
try:
    from crypto_ai_bot.core.storage.repositories.decisions import SqliteDecisionsRepository
except Exception:
    SqliteDecisionsRepository = None  # type: ignore

try:
    from crypto_ai_bot.app.bus_wiring import make_bus, snapshot_quantiles
except Exception:
    class _DummyBus:
        def publish(self, event: Dict[str, Any]) -> None: ...
        def subscribe(self, type_: str, handler) -> None: ...
        def health(self) -> Dict[str, Any]: return {"dlq_size": 0, "status": "ok"}
    def make_bus(): return _DummyBus()
    def snapshot_quantiles(): return {}

app = FastAPI(title="crypto-ai-bot")

CFG = Settings.build()
init_logging(level=CFG.log_level, json_format=CFG.log_json)
HTTP = get_http_client()
BREAKER = CircuitBreaker()

# DB & repos
CONN = connect(CFG.db_path)
class _Repos:
    def __init__(self, con):
        self.positions = SqlitePositionRepository(con)
        self.trades = SqliteTradeRepository(con)
        self.audit = SqliteAuditRepository(con)
        self.idempotency = SqliteIdempotencyRepository(con)
        self.uow = SqliteUnitOfWork(con)
        self.decisions = SqliteDecisionsRepository(con) if SqliteDecisionsRepository else None
REPOS = _Repos(CONN)

BUS = make_bus()
BROKER = create_broker(CFG, bus=BUS)

@app.get("/health")
async def health() -> JSONResponse:
    try:
        CONN.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False

    try:
        broker_ok = bool(BROKER.fetch_ticker(CFG.symbol))
    except Exception:
        broker_ok = False

    try:
        bus_health = BUS.health() if hasattr(BUS, "health") else {}
        dlq = int(bus_health.get("dlq_size") or 0)
    except Exception:
        bus_health = {}
        dlq = 0

    # --- time drift ---
    drift_ms = None
    drift_ok = True
    try:
        if measure_time_drift is not None:
            drift_ms = int(measure_time_drift(cfg=CFG, http=HTTP, urls=CFG.time_drift_urls, timeout=CFG.context_http_timeout_sec))  # type: ignore
            drift_ok = drift_ms <= int(CFG.max_time_drift_ms)
    except Exception:
        drift_ok = True  # не роняем health из-за этой проверки

    status = "healthy"
    if not db_ok or not broker_ok:
        status = "unhealthy"
    elif dlq > 0 or not drift_ok:
        status = "degraded"

    return JSONResponse({
        "status": status,
        "db": db_ok,
        "broker": broker_ok,
        "bus": bus_health,
        "dlq": dlq,
        "mode": CFG.mode,
        "symbol": CFG.symbol,
        "timeframe": CFG.timeframe,
        "time_drift_ms": drift_ms,
        "max_time_drift_ms": int(CFG.max_time_drift_ms),
        "time_drift_ok": drift_ok,
    })

@app.get("/metrics")
async def metrics_endpoint():
    text = metrics.export_as_text()
    return PlainTextResponse(text, media_type="text/plain; version=0.0.4")

@app.get("/status/extended")
async def status_extended() -> JSONResponse:
    snap = sqlite_snapshot(CONN)
    q = snapshot_quantiles()
    b = BUS.health() if hasattr(BUS, "health") else {}
    return JSONResponse({"sqlite": snap, "quantiles": q, "bus": b})

@app.post("/telegram")
async def telegram_webhook(request: Request, x_telegram_secret_token: Optional[str] = Header(default=None)) -> JSONResponse:
    expected = CFG.telegram_webhook_secret
    if expected and (x_telegram_secret_token != expected):
        return JSONResponse({"ok": False, "error": "invalid webhook secret"}, status_code=401)
    try:
        update = await request.json()
    except Exception:
        update = {}
    try:
        resp = await tg_adapter.handle(update, cfg=CFG, broker=BROKER, repos=REPOS, bus=BUS, http=HTTP)
    except Exception as e:
        resp = {"status": "error", "error": f"{type(e).__name__}: {e}"}
    return JSONResponse(resp)

@app.post("/dry/evaluate")
async def dry_evaluate(
    symbol: Optional[str] = Query(None),
    timeframe: Optional[str] = Query(None),
    limit: int = Query(200),
) -> JSONResponse:
    sym = normalize_symbol(symbol or CFG.symbol)
    tf = normalize_timeframe(timeframe or CFG.timeframe)
    d = uc_evaluate(CFG, BROKER, symbol=sym, timeframe=tf, limit=limit, repos=REPOS, http=HTTP)
    return JSONResponse(d)
