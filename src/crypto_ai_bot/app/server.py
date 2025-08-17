# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, Request, Body, Query, Header
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.logging import init as init_logging
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils.http_client import get_http_client

from crypto_ai_bot.app.adapters import telegram as tg_adapter

from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe

from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute

from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.uow import SqliteUnitOfWork
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
try:
    from crypto_ai_bot.core.storage.repositories.decisions import SqliteDecisionsRepository
except Exception:
    SqliteDecisionsRepository = None

# time drift
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift
except Exception:
    def measure_time_drift(cfg=None, http=None, *, urls: Optional[List[str]] = None, timeout: float = 1.5) -> Optional[int]:
        return None

# bus wiring
from crypto_ai_bot.app.bus_wiring import build_bus

# orchestrator (опционально)
try:
    from crypto_ai_bot.core.orchestrator import Orchestrator, set_global_orchestrator
except Exception:
    Orchestrator = None  # type: ignore

app = FastAPI(title="crypto-ai-bot")
init_logging()

CFG: Settings = Settings.build()
BREAKER = CircuitBreaker()
HTTP = get_http_client()

CONN = connect(getattr(CFG, "DB_PATH", "crypto.db"))

# Контейнер репозиториев, совместимый с контрактом use_cases.eval_and_execute()
class _Repos:
    def __init__(self, con):
        self.positions = SqlitePositionRepository(con)
        self.trades = SqliteTradeRepository(con)
        self.audit = SqliteAuditRepository(con)
        self.uow = SqliteUnitOfWork(con)
        self.idempotency = SqliteIdempotencyRepository(con)
        self.decisions = SqliteDecisionsRepository(con) if SqliteDecisionsRepository else None

REPOS = _Repos(CONN)

# Event Bus + брокер
BUS = build_bus(CFG, REPOS)
BROKER = create_broker(CFG, bus=BUS)

metrics.inc("app_start_total", {"mode": getattr(CFG, "MODE", "unknown")})
metrics.inc("broker_created_total", {"mode": getattr(CFG, "MODE", "unknown")})

# --- lifecycle: опциональный автозапуск оркестратора ---
_ORCH_TASK: Optional[asyncio.Task] = None

@app.on_event("startup")
async def _on_startup() -> None:
    global _ORCH_TASK
    if getattr(CFG, "ORCHESTRATOR_AUTOSTART", False) and Orchestrator is not None:
        orch = Orchestrator(CFG, BROKER, REPOS, bus=BUS)
        set_global_orchestrator(orch)  # type: ignore
        async def _runner():
            await orch.start()
            # живем пока приложение живо
            while True:
                await asyncio.sleep(3600)
        _ORCH_TASK = asyncio.create_task(_runner(), name="orch-runner")

@app.on_event("shutdown")
async def _on_shutdown() -> None:
    global _ORCH_TASK
    if _ORCH_TASK:
        _ORCH_TASK.cancel()
        _ORCH_TASK = None

def _safe_config(cfg: Settings) -> Dict[str, Any]:
    SAFE_PREFIXES = ("API_", "SECRET", "TOKEN", "PASSWORD", "WEBHOOK", "TELEGRAM")
    out: Dict[str, Any] = {}
    for k, v in vars(cfg).items():
        if k.startswith("__"):
            continue
        upper = k.upper()
        if any(p in upper for p in SAFE_PREFIXES):
            continue
        try:
            json.dumps(v)
            out[k] = v
        except TypeError:
            out[k] = str(v)
    return out


def _health_matrix(components: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    bad = sum(1 for c in components.values() if c.get("status", "ok") != "ok")
    if bad == 0:
        return {"status": "healthy", "degradation_level": "none"}
    if bad == 1:
        return {"status": "degraded", "degradation_level": "minor"}
    if bad == 2:
        return {"status": "degraded", "degradation_level": "major"}
    return {"status": "unhealthy", "degradation_level": "critical"}


@app.get("/health")
def health() -> JSONResponse:
    t0 = time.time()
    db_ok = True
    db_error = None
    try:
        CONN.execute("SELECT 1")
        db_latency_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        db_ok = False
        db_latency_ms = int((time.time() - t0) * 1000)
        db_error = f"{type(e).__name__}: {e}"

    b0 = time.time()
    broker_ok = True
    broker_detail = None
    try:
        BREAKER.call(
            lambda: BROKER.fetch_ticker(getattr(CFG, "SYMBOL", "BTC/USDT")),
            key="broker.fetch_ticker",
            timeout=2.0,
        )
    except Exception as e:
        broker_ok = False
        broker_detail = f"{type(e).__name__}: {e}"
    broker_latency_ms = int((time.time() - b0) * 1000)

    # drift
    drift_ms = measure_time_drift(CFG, HTTP, urls=getattr(CFG, "TIME_DRIFT_URLS", None) or None, timeout=1.5)
    limit = int(getattr(CFG, "TIME_DRIFT_LIMIT_MS", 1000))
    drift_status = "ok" if (drift_ms is not None and drift_ms <= limit) else ("unknown" if drift_ms is None else "error")

    # bus
    bus_state = {"status": "unknown"}
    try:
        bus_state = BUS.health()
    except Exception as e:
        bus_state = {"status": "error", "detail": f"{type(e).__name__}: {e}"}

    comps = {
        "mode": getattr(CFG, "MODE", "unknown"),
        "db": {"status": "ok" if db_ok else "error", "latency_ms": db_latency_ms, **({"detail": db_error} if not db_ok else {})},
        "broker": {"status": "ok" if broker_ok else "error", "latency_ms": broker_latency_ms, **({"detail": broker_detail} if not broker_ok else {})},
        "time": {"status": drift_status, "drift_ms": drift_ms if drift_ms is not None else -1, "limit_ms": limit},
        "bus": bus_state,
    }
    rollup = _health_matrix({k: v for k, v in comps.items() if isinstance(v, dict)})
    return JSONResponse({**rollup, "components": comps})


@app.get("/health/details")
def health_details() -> JSONResponse:
    return JSONResponse({"breakers": BREAKER.get_stats()})


@app.get("/metrics")
def metrics_export() -> PlainTextResponse:
    base = metrics.export()
    state_map = {"closed": 0, "half-open": 1, "open": 2}
    extra: List[str] = []
    stats = BREAKER.get_stats()
    for key, st in stats.items():
        sname = st.get("state", "closed")
        extra.append(f'breaker_state{{key="{key}"}} {state_map.get(sname, 0)}')
        counters = st.get("counters") or {}
        for cname, val in counters.items():
            extra.append(f'breaker_{cname}_total{{key="{key}"}} {int(val)}')
        extra.append(f'breaker_last_error_flag{{key="{key}"}} {1 if st.get("last_error") else 0}')
    payload = base.rstrip() + ("\n" if base and not base.endswith("\n") else "") + "\n".join(extra) + "\n"
    return PlainTextResponse(payload, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/config")
def config_public() -> JSONResponse:
    return JSONResponse(_safe_config(CFG))


@app.post("/tick")
def tick(body: Dict[str, Any] = Body(default=None)) -> JSONResponse:
    sym = normalize_symbol((body or {}).get("symbol") or getattr(CFG, "SYMBOL", "BTC/USDT"))
    tf = normalize_timeframe((body or {}).get("timeframe") or getattr(CFG, "TIMEFRAME", "1h"))
    limit = int((body or {}).get("limit") or getattr(CFG, "LIMIT_BARS", 300))
    try:
        decision = uc_eval_and_execute(CFG, BROKER, REPOS, symbol=sym, timeframe=tf, limit=limit, bus=BUS)
        return JSONResponse({"status": "ok", "decision": decision, "symbol": sym, "timeframe": tf})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"})


@app.get("/last")
def last(limit: int = Query(1, ge=1, le=200)) -> JSONResponse:
    if not getattr(REPOS, "decisions", None):
        return JSONResponse({"status": "error", "error": "decisions_repo_unavailable"})
    rows = REPOS.decisions.list_recent(limit=limit)
    return JSONResponse({"status": "ok", "items": rows})


@app.get("/positions/open")
def positions_open() -> JSONResponse:
    items = REPOS.positions.get_open() or []
    return JSONResponse({"status": "ok", "items": items})


@app.get("/orders/recent")
def orders_recent(limit: int = Query(50, ge=1, le=500)) -> JSONResponse:
    items = REPOS.trades.list_recent(limit=limit) or []
    return JSONResponse({"status": "ok", "items": items})


@app.post("/alerts/test")
def alerts_test(message: Optional[str] = Query(None)) -> JSONResponse:
    metrics.inc("alerts_test_total", {"mode": getattr(CFG, "MODE", "unknown")})
    return JSONResponse({"status": "ok", "echo": message or "pong"})


# --- Bus endpoints ---
@app.get("/bus/health")
def bus_health() -> JSONResponse:
    try:
        return JSONResponse({"status": "ok", "bus": BUS.health()})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"{type(e).__name__}: {e}"})


@app.get("/bus/dlq")
def bus_dlq(limit: int = Query(50, ge=1, le=1000)) -> JSONResponse:
    try:
        # у синхронного Bus это dlq_dump(); у адаптера можно сделать такую же сигнатуру
        items = BUS.dlq_dump(limit=limit)
    except AttributeError:
        items = []
    return JSONResponse({"status": "ok", "items": items})


@app.post("/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
) -> JSONResponse:
    secret = getattr(CFG, "TELEGRAM_WEBHOOK_SECRET", None)
    if secret and x_telegram_bot_api_secret_token != secret:
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    try:
        update = await request.json()
    except Exception:
        update = {}

    # адаптер ожидает broker и http-клиент; прокидываем bus
    resp = tg_adapter.handle_update(update, CFG, BROKER, HTTP, bus=BUS)
    return JSONResponse(resp)
