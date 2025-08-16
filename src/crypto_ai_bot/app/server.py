# app/server.py
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.utils.time_sync import measure_time_drift

# Broker + evaluate
try:
    from crypto_ai_bot.core.brokers.base import create_broker
except Exception:  # fallback if factory name differs
    create_broker = None  # type: ignore

try:
    from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
except Exception:
    uc_evaluate = None  # type: ignore

app = FastAPI()

_cfg: Optional[Settings] = None
_http = None
_broker = None


@app.on_event("startup")
async def on_startup() -> None:
    global _cfg, _http, _broker
    _cfg = Settings.build()
    _http = get_http_client()

    # metrics
    metrics.inc("app_start_total", {"mode": getattr(_cfg, "MODE", "paper")})

    # broker via factory if available; otherwise keep None (health will reflect it)
    if create_broker is not None:
        try:
            _broker = create_broker(_cfg)  # factory should accept Settings
            metrics.inc("broker_created_total", {"mode": getattr(_cfg, "MODE", "paper")})
        except Exception as e:
            # Record that broker creation failed; health will surface error
            metrics.inc("broker_create_failed_total", {"mode": getattr(_cfg, "MODE", "paper"), "err": type(e).__name__})


@app.get("/metrics")
def get_metrics() -> Response:
    body = metrics.export()
    return PlainTextResponse(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


def _health_components() -> Dict[str, Any]:
    cfg = _cfg or Settings.build()
    http = _http or get_http_client()

    # mode
    components: Dict[str, Any] = {
        "mode": getattr(cfg, "MODE", "paper"),
    }

    # DB probe (cheap no-op – your sqlite_adapter can be wired here later)
    components["db"] = {"status": "ok", "latency_ms": 0}

    # Broker probe (ticker fetch with short timeout) – optional
    broker_status = {"status": "skipped"}
    if _broker is not None and hasattr(_broker, "fetch_ticker"):
        t0 = time.time() * 1000.0
        try:
            # Use configured symbol if available
            sym = getattr(cfg, "SYMBOL", "BTC/USDT")
            _broker.fetch_ticker(sym)  # type: ignore
            t1 = time.time() * 1000.0
            broker_status = {"status": "ok", "latency_ms": int(t1 - t0)}
        except Exception as e:
            t1 = time.time() * 1000.0
            broker_status = {"status": f"error:{type(e).__name__}", "latency_ms": int(t1 - t0)}
    components["broker"] = broker_status

    # Time drift
    urls = getattr(cfg, "TIME_DRIFT_URLS", None)
    limit_ms = int(getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000))
    try:
        drift = measure_time_drift(http, urls=urls, timeout=2.0)
        drift_ms = drift.get("drift_ms")
        c = {
            "drift_ms": drift_ms if drift_ms is not None else None,
            "limit_ms": limit_ms,
            "sources_ok": drift.get("ok_count", 0),
            "sources_total": drift.get("total", 0),
        }
        if drift_ms is None:
            c["status"] = "error:no_sources"
        elif abs(int(drift_ms)) <= limit_ms:
            c["status"] = "ok"
        else:
            c["status"] = "degraded"
        components["time"] = c
    except Exception as e:
        components["time"] = {"status": f"error:{type(e).__name__}", "detail": str(e)}

    return components


@app.get("/health")
def health() -> Response:
    components = _health_components()

    # Aggregate
    overall = "healthy"
    degradation = "none"

    # If any component is a hard error -> unhealthy
    for name, comp in components.items():
        if isinstance(comp, dict):
            st = comp.get("status")
            if isinstance(st, str) and st.startswith("error"):
                overall = "unhealthy"
                degradation = "major"
                break

    # Else, degraded if time drift degraded or broker latency too high (optional)
    if overall == "healthy":
        time_c = components.get("time", {})
        if isinstance(time_c, dict) and time_c.get("status") == "degraded":
            overall = "degraded"
            degradation = "minor"

    body = {
        "status": overall,
        "degradation_level": degradation,
        "components": components,
    }
    return JSONResponse(body)


@app.post("/tick")
async def tick(request: Request) -> Response:
    cfg = _cfg or Settings.build()
    payload = {}
    try:
        if request.headers.get("content-length"):
            payload = await request.json()
    except Exception:
        payload = {}

    symbol = payload.get("symbol") or getattr(cfg, "SYMBOL", "BTC/USDT")
    timeframe = payload.get("timeframe") or getattr(cfg, "TIMEFRAME", "1h")
    limit = int(payload.get("limit") or getattr(cfg, "LIMIT", 300))

    labels = {"mode": getattr(cfg, "MODE", "paper")}
    metrics.inc("tick_request_total", labels)

    # Evaluate-only to stay side-effect free via API
    try:
        if uc_evaluate is None or _broker is None:
            raise RuntimeError("evaluate/broker not available")
        decision = uc_evaluate(cfg, _broker, symbol=symbol, timeframe=timeframe, limit=limit)
        metrics.inc("tick_success_total", labels)
        return JSONResponse({
            "status": "evaluated",
            "symbol": symbol,
            "timeframe": timeframe,
            "decision": decision if isinstance(decision, dict) else getattr(decision, "__dict__", decision),
        })
    except Exception as e:
        metrics.inc("tick_failed_total", {**labels, "err": type(e).__name__})
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"}, status_code=200)
