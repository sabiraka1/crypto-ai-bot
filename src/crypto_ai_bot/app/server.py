# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import json
import os
import time
from collections import deque
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.time_sync import measure_time_drift_ms

# Bus (async, с фолбэком на sync)
try:
    from crypto_ai_bot.core.events.async_bus import AsyncBus as _BusImpl  # type: ignore
except Exception:
    from crypto_ai_bot.core.events.bus import Bus as _BusImpl  # type: ignore

# UC
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute

# фабрика брокера/символы
from crypto_ai_bot.core.brokers import create_broker, normalize_symbol, normalize_timeframe

# фабрика репозиториев (упрощённая заглушка: ожидается, что в проекте есть такая сборка)
try:
    from crypto_ai_bot.core.storage.repositories import (
        SqliteTradeRepository,
        SqlitePositionRepository,
        SqliteAuditRepository,
        SqliteIdempotencyRepository,
    )
    from crypto_ai_bot.core.storage.sqlite_adapter import connect
except Exception:
    SqliteTradeRepository = SqlitePositionRepository = SqliteAuditRepository = SqliteIdempotencyRepository = None  # type: ignore
    connect = None  # type: ignore

app = FastAPI(title="crypto-ai-bot")

# --- Глобальное состояние приложения
_cfg: Settings
_broker: Any
_bus: Any
_repos: Any

# Ринг-буфер событий для быстрой диагностики
_EVENTS_RING = deque(maxlen=200)

def _bus_subscribe_debug(bus: Any) -> None:
    """Подписываемся на все ключевые события и складываем в кольцевой буфер."""
    topics = (
        "DecisionEvaluated",
        "RiskChecked",
        "OrderSkipped",
        "OrderBlocked",
        "OrderExecuted",
        "FlowFinished",
        "HealthDegraded",
    )
    for t in topics:
        try:
            bus.subscribe(t, lambda evt, _t=t: _EVENTS_RING.append(evt))
        except Exception:
            pass

def _set_gauge(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    """Безопасно выставляем gauge, если реализован."""
    try:
        fn = getattr(metrics, "set_gauge", None)
        if callable(fn):
            fn(name, value, labels or {})
            return
    except Exception:
        pass
    # Фолбэк: “прибитый” observe (не настоящий gauge, но лучше чем ничего)
    metrics.observe(f"{name}_value", value, labels or {})

def _map_rollup_to_degradation(status: str, components: Dict[str, Any], cfg: Settings) -> str:
    """
    Синхронизация с картой статусов из спецификации:
      - healthy   → "none"
      - degraded  → "no_trading"
      - unhealthy → "critical"
    (просто и прозрачно)
    """
    if status == "healthy":
        return "none"
    if status == "degraded":
        return "no_trading"
    return "critical"  # unhealthy и всё прочее

@app.on_event("startup")
async def on_startup() -> None:
    global _cfg, _broker, _bus, _repos

    _cfg = Settings.build()
    _bus = _BusImpl()
    _bus_subscribe_debug(_bus)

    # брокер через фабрику
    _broker = create_broker(_cfg)

    # простая сборка репозиториев (если доступно)
    class _Repos:
        pass

    _repos = _Repos()
    if connect and all([SqliteTradeRepository, SqlitePositionRepository, SqliteAuditRepository]):
        con = connect(_cfg.DB_PATH)
        _repos.trades = SqliteTradeRepository(con)  # type: ignore
        _repos.positions = SqlitePositionRepository(con)  # type: ignore
        _repos.audit = SqliteAuditRepository(con)  # type: ignore
        _repos.idempotency = SqliteIdempotencyRepository(con) if SqliteIdempotencyRepository else None  # type: ignore
        # минимальный UoW (если в проекте есть полноценный — он будет использован там, где импортируется)
        _repos.uow = getattr(_repos, "uow", None)

    metrics.inc("app_start_total", {"mode": _cfg.MODE})
    _bus.publish({"type": "AppStarted", "mode": _cfg.MODE})

@app.get("/health")
async def health() -> JSONResponse:
    """
    Композитный health + time drift gauge + карта статусов (none/no_trading/critical).
    """
    started = time.perf_counter()

    # DB
    db_ok, db_latency = True, 0
    try:
        t0 = time.perf_counter()
        # “прощупать” репозитории, если есть
        if getattr(_repos, "trades", None) and hasattr(_repos.trades, "ping"):
            _repos.trades.ping()
        db_latency = int((time.perf_counter() - t0) * 1000)
    except Exception:
        db_ok = False
        db_latency = int((time.perf_counter() - started) * 1000)

    # Broker
    br_ok, br_latency, br_detail = True, 0, None
    try:
        t1 = time.perf_counter()
        _ = await _maybe_async_fetch_ticker(_broker, _cfg.SYMBOL)
        br_latency = int((time.perf_counter() - t1) * 1000)
    except Exception as e:
        br_ok = False
        br_detail = f"{type(e).__name__}"
        br_latency = int((time.perf_counter() - started) * 1000)

    # Time drift (с гейджем)
    drift_ms, drift_urls = 0, []
    try:
        drift_ms, drift_urls = await measure_time_drift_ms(_cfg)
        _set_gauge("time_drift_ms", float(drift_ms), {"mode": _cfg.MODE})
    except Exception:
        pass

    # rollup
    status = "healthy"
    if (not db_ok) or (not br_ok):
        status = "unhealthy"
    elif (drift_ms > _cfg.TIME_DRIFT_LIMIT_MS) or (db_latency > 1000) or (br_latency > 2000):
        status = "degraded"

    degradation_level = _map_rollup_to_degradation(status, {}, _cfg)

    result = {
        "status": status,
        "degradation_level": degradation_level,
        "components": {
            "mode": _cfg.MODE,
            "db": {"status": "ok" if db_ok else "error", "latency_ms": db_latency},
            "broker": {"status": "ok" if br_ok else f"error:{br_detail or 'unknown'}", "latency_ms": br_latency},
            "time": {
                "status": "ok" if drift_ms <= _cfg.TIME_DRIFT_LIMIT_MS else "drift",
                "drift_ms": drift_ms,
                "limit_ms": _cfg.TIME_DRIFT_LIMIT_MS,
                "sources": drift_urls,
            },
        },
    }

    # сигнал деградации (переход)
    prev = getattr(app.state, "_last_health_status", None)
    app.state._last_health_status = result["status"]
    if prev in (None, "healthy") and result["status"] in ("degraded", "unhealthy"):
        try:
            _bus.publish({"type": "HealthDegraded", "from": prev or "none", "to": result["status"], "components": result["components"]})
        except Exception:
            pass

    return JSONResponse(result)

async def _maybe_async_fetch_ticker(broker: Any, symbol: str) -> Dict[str, Any]:
    """Брокер может быть sync — приведём к общему виду."""
    res = broker.fetch_ticker(symbol)
    return res

@app.get("/metrics")
async def metrics_export() -> PlainTextResponse:
    return PlainTextResponse(metrics.export(), media_type="text/plain; version=0.0.4; charset=utf-8")

@app.post("/tick")
async def tick(req: Request) -> JSONResponse:
    payload = {}
    try:
        payload = await req.json()
    except Exception:
        pass
    symbol = normalize_symbol(payload.get("symbol") or _cfg.SYMBOL)
    timeframe = normalize_timeframe(payload.get("timeframe") or _cfg.TIMEFRAME)
    limit = int(payload.get("limit") or getattr(_cfg, "LIMIT_BARS", 300))

    try:
        decision = uc_evaluate(_cfg, _broker, symbol=symbol, timeframe=timeframe, limit=limit, bus=_bus)
        return JSONResponse({"status": "evaluated", "symbol": symbol, "timeframe": timeframe, "decision": decision})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"})

@app.post("/trade")
async def trade(req: Request) -> JSONResponse:
    payload = {}
    try:
        payload = await req.json()
    except Exception:
        pass
    symbol = normalize_symbol(payload.get("symbol") or _cfg.SYMBOL)
    timeframe = normalize_timeframe(payload.get("timeframe") or _cfg.TIMEFRAME)
    limit = int(payload.get("limit") or getattr(_cfg, "LIMIT_BARS", 300))

    try:
        result = uc_eval_and_execute(_cfg, _broker, _repos, symbol=symbol, timeframe=timeframe, limit=limit, bus=_bus)
        return JSONResponse({"status": "ok", "result": result})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"trade_failed: {type(e).__name__}: {e}"})

@app.get("/events/debug")
async def events_debug(limit: int = 50) -> JSONResponse:
    out = list(_EVENTS_RING)[-int(limit):]
    return JSONResponse({"events": out, "count": len(out)})

@app.get("/bus/stats")
async def bus_stats() -> JSONResponse:
    try:
        stats = _bus.stats()
    except Exception:
        stats = {"queue_len": len(_EVENTS_RING)}
    return JSONResponse({"bus": stats})

@app.get("/config")
async def config_dump() -> JSONResponse:
    # показать ключевые поля (включая METRICS_REFRESH_SEC)
    data = {
        "MODE": _cfg.MODE,
        "SYMBOL": _cfg.SYMBOL,
        "TIMEFRAME": _cfg.TIMEFRAME,
        "ENABLE_TRADING": getattr(_cfg, "ENABLE_TRADING", False),
        "TIME_DRIFT_LIMIT_MS": getattr(_cfg, "TIME_DRIFT_LIMIT_MS", 1000),
        "TIME_DRIFT_URLS": getattr(_cfg, "TIME_DRIFT_URLS", []),
        "METRICS_REFRESH_SEC": getattr(_cfg, "METRICS_REFRESH_SEC", 30),
    }
    return JSONResponse(data)
