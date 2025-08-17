# src/crypto_ai_bot/app/server.py
from __future__ import annotations

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
from crypto_ai_bot.utils.time_sync import measure_time_drift

from crypto_ai_bot.core.bot import Bot
from crypto_ai_bot.app.adapters import telegram as tg_adapter
from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe


app = FastAPI(title="crypto-ai-bot")
init_logging()

CFG: Settings = Settings.build()
BREAKER = CircuitBreaker()
HTTP = get_http_client()
BOT = Bot(CFG)  # внутри создаёт брокера, UoW и репозитории

metrics.inc("app_start_total", {"mode": getattr(CFG, "MODE", "unknown")})

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
    """
    Матрица: healthy / degraded / unhealthy
    DB ok + Broker ok + TimeSync ok → healthy
    DB ok + Broker fail (Transient) + TimeSync ok → degraded
    DB fail ИЛИ TimeSync drift > 1s → unhealthy
    """
    db_ok = components.get("db", {}).get("status") == "ok"
    br_ok = components.get("broker", {}).get("status") == "ok"
    tm_ok = components.get("time", {}).get("status") == "ok"
    if db_ok and br_ok and tm_ok:
        return {"status": "healthy", "degradation_level": "none"}
    if db_ok and (not br_ok) and tm_ok:
        return {"status": "degraded", "degradation_level": "minor"}
    return {"status": "unhealthy", "degradation_level": "critical"}  # всё остальное


@app.get("/health")
def health() -> JSONResponse:
    # DB
    t0 = time.time()
    db_ok = True
    db_error: Optional[str] = None
    try:
        BOT.con.execute("SELECT 1")
    except Exception as e:
        db_ok = False
        db_error = f"{type(e).__name__}: {e}"
    db_latency_ms = int((time.time() - t0) * 1000)

    # Broker (через breaker)
    b0 = time.time()
    broker_ok = True
    broker_detail: Optional[str] = None
    try:
        # CircuitBreaker.call принимает только fn/key/timeout/... → оборачиваем вызов в лямбду
        BREAKER.call(
            lambda: BOT.broker.fetch_ticker(getattr(CFG, "SYMBOL", "BTC/USDT")),
            key="broker.fetch_ticker",
            timeout=2.0,
        )
    except Exception as e:
        broker_ok = False
        broker_detail = f"{type(e).__name__}: {e}"
    broker_latency_ms = int((time.time() - b0) * 1000)

    # Time sync (возвращает int миллисекунд или None)
    drift_ms: Optional[int] = measure_time_drift(cfg=CFG, http=HTTP, urls=CFG.TIME_DRIFT_URLS or None, timeout=1.5)
    limit = int(getattr(CFG, "TIME_DRIFT_LIMIT_MS", 1000))
    time_status = "ok" if (drift_ms is not None and drift_ms <= limit) else "error"

    comps = {
        "mode": getattr(CFG, "MODE", "unknown"),
        "db": {
            "status": "ok" if db_ok else "error",
            "latency_ms": db_latency_ms,
            **({"detail": db_error} if not db_ok else {}),
        },
        "broker": {
            "status": "ok" if broker_ok else "error",
            "latency_ms": broker_latency_ms,
            **({"detail": broker_detail} if not broker_ok else {}),
        },
        "time": {
            "status": time_status,
            "drift_ms": (drift_ms if drift_ms is not None else -1),
            "limit_ms": limit,
            "sources": CFG.TIME_DRIFT_URLS,
        },
    }
    rollup = _health_matrix(comps)
    return JSONResponse({**rollup, "components": comps})


@app.get("/metrics")
def metrics_export() -> PlainTextResponse:
    """
    Экспорт системных метрик + состояния circuit breaker.
    """
    base = metrics.export()

    state_map = {"closed": 0, "half-open": 1, "open": 2}
    extra: List[str] = []
    stats = BREAKER.get_stats()
    for key, st in stats.items():
        sname = st.get("state", "closed")
        extra.append(f'broker_circuit_state{{key="{key}"}} {state_map.get(sname, 0)}')
        counters = st.get("counters") or {}
        for cname, val in counters.items():
            extra.append(f'broker_circuit_{cname}_total{{key="{key}"}} {int(val)}')
        extra.append(f'broker_circuit_last_error_flag{{key="{key}"}} {1 if st.get("last_error") else 0}')

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
        decision = BOT.eval_and_execute(symbol=sym, timeframe=tf, limit=limit)
        # обновим метрики трекера, если есть
        tracker = getattr(BOT, "positions_repo", None) and getattr(BOT, "trades_repo", None)
        if tracker:
            try:
                from crypto_ai_bot.core.positions.tracker import PositionTracker  # локальный импорт
                PositionTracker(BOT.positions_repo, BOT.trades_repo).update_metrics()
            except Exception:
                pass
        return JSONResponse({"status": "ok", "decision": decision, "symbol": sym, "timeframe": tf})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"})


@app.post("/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
) -> JSONResponse:
    # Верификация секрета по заголовку
    secret = getattr(CFG, "TELEGRAM_SECRET_TOKEN", None)
    if secret and x_telegram_bot_api_secret_token != secret:
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    try:
        update = await request.json()
    except Exception:
        update = {}

    # Адаптер синхронный: http-клиент обязателен согласно контракту
    resp = tg_adapter.handle_update(update, CFG, BOT, HTTP)
    return JSONResponse(resp)
