# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import os
import json
import time
from typing import Any, Dict, Optional, List
from fastapi import FastAPI, Request, Body, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.logging import init as init_logging
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker

# фабрика брокера и нормализация
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe

# use-cases
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order as uc_place_order
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute

# storage (sqlite + репозитории)
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository
try:
    from crypto_ai_bot.core.storage.repositories.decisions import SqliteDecisionsRepository
except Exception:
    SqliteDecisionsRepository = None  # опционально

# опционально — проверка дрифта времени
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift
except Exception:
    def measure_time_drift(urls: Optional[List[str]] = None, timeout: float = 1.5) -> Dict[str, Any]:
        return {"drift_ms": 0, "limit_ms": 0, "sources": [], "status": "unknown"}


app = FastAPI(title="crypto-ai-bot")
init_logging()

# --- singletons ---
CFG: Settings = Settings.build()
BREAKER = CircuitBreaker()
CONN = connect(getattr(CFG, "DB_PATH", "crypto.db"))
REPOS = type("Repos", (), {})()
REPOS.positions = SqlitePositionRepository(CONN)
REPOS.trades = SqliteTradeRepository(CONN)
REPOS.audit = SqliteAuditRepository(CONN)
REPOS.decisions = SqliteDecisionsRepository(CONN) if SqliteDecisionsRepository else None

BROKER = create_broker(
    mode=getattr(CFG, "MODE", "paper"),
    settings=CFG,
    circuit_breaker=BREAKER,
)

metrics.inc("app_start_total", {"mode": getattr(CFG, "MODE", "unknown")})
metrics.inc("broker_created_total", {"mode": getattr(CFG, "MODE", "unknown")})


# ------------ helpers ------------

SAFE_PREFIXES = ("API_", "SECRET", "TOKEN", "PASSWORD", "WEBHOOK", "TELEGRAM")

def _safe_config(cfg: Settings) -> Dict[str, Any]:
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
    bad = 0
    for c in components.values():
        st = c.get("status", "ok")
        if st != "ok":
            bad += 1

    if bad == 0:
        return {"status": "healthy", "degradation_level": "none"}
    if bad == 1:
        return {"status": "degraded", "degradation_level": "minor"}
    if bad == 2:
        return {"status": "degraded", "degradation_level": "major"}
    return {"status": "unhealthy", "degradation_level": "critical"}


# ------------ endpoints ------------

@app.get("/health")
def health() -> JSONResponse:
    t0 = time.time()
    # DB ping
    db_ok = True
    try:
        CONN.execute("SELECT 1")
        db_latency_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        db_ok = False
        db_latency_ms = int((time.time() - t0) * 1000)
        db_error = f"{type(e).__name__}: {e}"

    # broker ping
    b0 = time.time()
    broker_ok = True
    broker_detail = None
    try:
        BREAKER.call(
            BROKER.fetch_ticker,
            key="broker.fetch_ticker",
            timeout=2.0,
            fallback=lambda: {"symbol": getattr(CFG, "SYMBOL", "BTC/USDT"), "price": None},
            symbol=getattr(CFG, "SYMBOL", "BTC/USDT"),
        )
    except Exception as e:
        broker_ok = False
        broker_detail = f"{type(e).__name__}: {e}"
    broker_latency_ms = int((time.time() - b0) * 1000)

    # time drift
    drift = measure_time_drift(
        urls=getattr(CFG, "TIME_DRIFT_URLS", []) or None,
        timeout=1.5,
    )
    drift_status = "ok"
    if isinstance(drift, dict):
        limit = int(drift.get("limit_ms", getattr(CFG, "TIME_DRIFT_LIMIT_MS", 1000)))
        if int(drift.get("drift_ms", 0)) > limit:
            drift_status = "error"

    comps = {
        "mode": getattr(CFG, "MODE", "unknown"),
        "db": {"status": "ok" if db_ok else f"error", "latency_ms": db_latency_ms, **({"detail": db_error} if not db_ok else {})},
        "broker": {"status": "ok" if broker_ok else f"error", "latency_ms": broker_latency_ms, **({"detail": broker_detail} if not broker_ok else {})},
        "time": {"status": drift_status, **drift},
    }
    rollup = _health_matrix({k: v for k, v in comps.items() if isinstance(v, dict)})
    return JSONResponse({**rollup, "components": comps})


@app.get("/health/details")
def health_details() -> JSONResponse:
    return JSONResponse({
        "breakers": BREAKER.get_stats(),
    })


@app.get("/metrics")
def metrics_export() -> PlainTextResponse:
    base = metrics.export()
    # динамически добавим состояния предохранителей
    # state: closed=0, half-open=1, open=2
    state_map = {"closed": 0, "half-open": 1, "open": 2}
    extra_lines: List[str] = []
    stats = BREAKER.get_stats()
    for key, st in stats.items():
        st_name = st.get("state", "closed")
        extra_lines.append(f'breaker_state{{key="{key}"}} {state_map.get(st_name, 0)}')
        counters = st.get("counters") or {}
        for cname, val in counters.items():
            extra_lines.append(f'breaker_{cname}_total{{key="{key}"}} {int(val)}')
        if st.get("last_error"):
            # Для текстов лучше не дублировать каждый раз — но дадим флаг наличия
            extra_lines.append(f'breaker_last_error_flag{{key="{key}"}} 1')
        else:
            extra_lines.append(f'breaker_last_error_flag{{key="{key}"}} 0')
    payload = base.rstrip() + ("\n" if base and not base.endswith("\n") else "") + "\n".join(extra_lines) + "\n"
    return PlainTextResponse(payload, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/config")
def config_public() -> JSONResponse:
    return JSONResponse(_safe_config(CFG))


@app.post("/tick")
def tick(body: Dict[str, Any] = Body(default=None)) -> JSONResponse:
    sym = normalize_symbol((body or {}).get("symbol") or getattr(CFG, "SYMBOL", "BTC/USDT"))
    tf = normalize_timeframe((body or {}).get("timeframe") or getattr(CFG, "TIMEFRAME", "1h"))
    limit = int((body or {}).get("limit") or getattr(CFG, "LIMIT", 300))
    try:
        decision = uc_eval_and_execute(CFG, BROKER, REPOS, symbol=sym, timeframe=tf, limit=limit)
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
    """
    Пробный хук для будущей интеграции алёртов/мониторинга.
    Пока просто увеличивает метрику и возвращает echo.
    """
    metrics.inc("alerts_test_total", {"mode": getattr(CFG, "MODE", "unknown")})
    return JSONResponse({"status": "ok", "echo": message or "pong"})
