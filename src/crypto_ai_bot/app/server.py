# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, Request, Body, Query, Header
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.logging import init as init_logging
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.utils.alerts import AlertState, send_telegram_alert

from fastapi.responses import Response
from crypto_ai_bot.utils.charts import render_price_spark_svg, render_profit_curve_svg, closes_from_ohlcv
from crypto_ai_bot.core.validators import validate_config

from crypto_ai_bot.app.adapters import telegram as tg_adapter

from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe

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
    SqliteDecisionsRepository = None

# журнал событий
from crypto_ai_bot.core.storage.repositories.events_journal import EventJournalRepository

# валидатор конфига
from crypto_ai_bot.core.validators import validate_config

# time drift
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift
except Exception:
    def measure_time_drift(cfg=None, http=None, *, urls: Optional[List[str]] = None, timeout: float = 1.5) -> Optional[int]:
        return None

# bus wiring + квантили
from crypto_ai_bot.app.bus_wiring import build_bus, snapshot_quantiles

# market context
from crypto_ai_bot.market_context.snapshot import build_snapshot as build_market_context

# charts (SVG)
from crypto_ai_bot.utils.charts import render_price_spark_svg, render_profit_curve_svg

# middleware
from crypto_ai_bot.app.middleware import register_middlewares

# orchestrator (опционально)
try:
    from crypto_ai_bot.core.orchestrator import Orchestrator, set_global_orchestrator
except Exception:
    Orchestrator = None  # type: ignore

app = FastAPI(title="crypto-ai-bot")
CFG: Settings = Settings.build()
init_logging(level=getattr(CFG, "LOG_LEVEL", "INFO"), json_format=bool(getattr(CFG, "LOG_JSON", False)))
register_middlewares(app)

BREAKER = CircuitBreaker()
HTTP = get_http_client()

CONN = connect(getattr(CFG, "DB_PATH", "crypto.db"))

class _Repos:
    def __init__(self, con):
        self.positions = SqlitePositionRepository(con)
        self.trades = SqliteTradeRepository(con)
        self.audit = SqliteAuditRepository(con)
        self.uow = SqliteUnitOfWork(con)
        self.idempotency = SqliteIdempotencyRepository(con)
        self.decisions = SqliteDecisionsRepository(con) if SqliteDecisionsRepository else None
        self.journal = EventJournalRepository(con, max_rows=int(getattr(CFG, "JOURNAL_MAX_ROWS", 10_000)))

REPOS = _Repos(CONN)

BUS = build_bus(CFG, REPOS)
BROKER = create_broker(CFG, bus=BUS)

metrics.inc("app_start_total", {"mode": getattr(CFG, "MODE", "unknown")})
metrics.inc("broker_created_total", {"mode": getattr(CFG, "MODE", "unknown")})

_ORCH_TASK: Optional[asyncio.Task] = None
_ALERT_TASK: Optional[asyncio.Task] = None
_ALERTS = AlertState()

@app.on_event("startup")
async def _on_startup() -> None:
    global _ORCH_TASK, _ALERT_TASK
    if getattr(CFG, "ORCHESTRATOR_AUTOSTART", False) and Orchestrator is not None:
        orch = Orchestrator(CFG, BROKER, REPOS, bus=BUS, http=HTTP)
        set_global_orchestrator(orch)  # type: ignore
        async def _runner():
            await orch.start()
            while True:
                await asyncio.sleep(3600)
        _ORCH_TASK = asyncio.create_task(_runner(), name="orch-runner")

    _ALERT_TASK = asyncio.create_task(_alerts_runner(), name="alerts-runner")


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    global _ORCH_TASK, _ALERT_TASK
    if _ORCH_TASK:
        _ORCH_TASK.cancel()
        _ORCH_TASK = None
    if _ALERT_TASK:
        _ALERT_TASK.cancel()
        _ALERT_TASK = None


async def _alerts_runner() -> None:
    cooldown_dlq = int(getattr(CFG, "ALERT_DLQ_EVERY_SEC", 300))
    cooldown_p99 = 300
    while True:
        try:
            if getattr(CFG, "ALERT_ON_DLQ", True):
                size = 0
                try:
                    h = BUS.health()
                    size = int(h.get("dlq_size") or h.get("dlq_len") or h.get("dlq", 0) or 0)
                except Exception:
                    size = 0
                if size > 0 and _ALERTS.should_send("dlq", cooldown_sec=cooldown_dlq, value=size):
                    _try_alert(f"⚠️ <b>DLQ</b>: {size} сообщений в очереди ошибок.")

            if getattr(CFG, "ALERT_ON_LATENCY", False):
                snap = snapshot_quantiles()
                thr_dec = int(getattr(CFG, "DECISION_LATENCY_P99_ALERT_MS", 0))
                thr_ord = int(getattr(CFG, "ORDER_LATENCY_P99_ALERT_MS", 0))
                thr_flow = int(getattr(CFG, "FLOW_LATENCY_P99_ALERT_MS", 0))

                def _maybe_alert(prefix: str, thr: int):
                    if thr <= 0:
                        return
                    for key, vv in snap.items():
                        if not key.startswith(prefix):
                            continue
                        p99 = float(vv.get("p99", 0.0))
                        if p99 and p99 > thr and _ALERTS.should_send(f"p99:{key}", cooldown_sec=cooldown_p99, value=int(p99)):
                            _try_alert(f"⏱️ <b>{prefix} p99</b> {key} = {int(p99)}ms > {thr}ms")

                _maybe_alert("decision:", thr_dec)
                _maybe_alert("order:", thr_ord)
                _maybe_alert("flow:", thr_flow)

        except asyncio.CancelledError:
            break
        except Exception:
            pass
        await asyncio.sleep(5)


def _try_alert(text: str) -> None:
    token = getattr(CFG, "TELEGRAM_BOT_TOKEN", None)
    chat_id = getattr(CFG, "ALERT_TELEGRAM_CHAT_ID", None)
    ok = False
    if token and chat_id:
        ok = send_telegram_alert(HTTP, token, chat_id, text)
    metrics.inc("alerts_sent_total", {"ok": "1" if ok else "0"})


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
        BREAKER.call(lambda: BROKER.fetch_ticker(getattr(CFG, "SYMBOL", "BTC/USDT")), key="broker.fetch_ticker", timeout=2.0)
    except Exception as e:
        broker_ok = False
        broker_detail = f"{type(e).__name__}: {e}"
    broker_latency_ms = int((time.time() - b0) * 1000)

    breaker_state = "ok"
    try:
        stats = BREAKER.get_stats()
        critical_keys = {"fetch_ticker", "fetch_order_book", "fetch_ohlcv", "create_order"}
        open_crit = any((stats.get(k, {}).get("state") == "open") for k in critical_keys)
        if open_crit:
            breaker_state = "open"
    except Exception:
        breaker_state = "unknown"

    drift_ms = measure_time_drift(CFG, HTTP, urls=getattr(CFG, "TIME_DRIFT_URLS", None) or None, timeout=1.5)
    limit = int(getattr(CFG, "TIME_DRIFT_LIMIT_MS", 1000))
    drift_status = "ok" if (drift_ms is not None and drift_ms <= limit) else ("unknown" if drift_ms is None else "error")

    try:
        bus_state = BUS.health()
    except Exception as e:
        bus_state = {"status": "error", "detail": f"{type(e).__name__}: {e}"}

    comps = {
        "mode": getattr(CFG, "MODE", "unknown"),
        "db": {"status": "ok" if db_ok else "error", "latency_ms": db_latency_ms, **({"detail": db_error} if not db_ok else {})},
        "broker": {"status": "ok" if broker_ok else "error", "latency_ms": broker_latency_ms, **({"detail": broker_detail} if not broker_ok else {})},
        "breaker": {"status": breaker_state},
        "time": {"status": drift_status, "drift_ms": drift_ms if drift_ms is not None else -1, "limit_ms": limit},
        "bus": bus_state,
    }
    rollup = _health_matrix({k: v for k, v in comps.items() if isinstance(v, dict)})
    return JSONResponse({**rollup, "components": comps})


@app.get("/metrics")
def metrics_export() -> PlainTextResponse:
    try:
        _ = sqlite_snapshot(CONN)
    except Exception:
        pass

    try:
        h = BUS.health()
        dlq = int(h.get("dlq_size") or h.get("dlq_len") or h.get("dlq", 0) or 0)
        metrics.gauge("events_dead_letter_total", float(dlq))
    except Exception:
        metrics.gauge("events_dead_letter_total", 0.0)

    try:
        snap = snapshot_quantiles()
        thr_dec = int(getattr(CFG, "PERF_BUDGET_DECISION_P99_MS", 0))
        thr_ord = int(getattr(CFG, "PERF_BUDGET_ORDER_P99_MS", 0))
        thr_flow = int(getattr(CFG, "PERF_BUDGET_FLOW_P99_MS", 0))
        exceeded_any = False
        for key, vv in snap.items():
            p99 = float(vv.get("p99", 0.0))
            kind = "unknown"
            if key.startswith("decision:"): kind = "decision"
            elif key.startswith("order:"): kind = "order"
            elif key.startswith("flow:"): kind = "flow"
            thr = {"decision": thr_dec, "order": thr_ord, "flow": thr_flow}.get(kind, 0)
            if thr > 0 and p99 and p99 > thr:
                metrics.gauge("performance_budget_exceeded", 1.0, {"type": kind, "key": key})
                exceeded_any = True
        metrics.gauge("performance_budget_exceeded_any", 1.0 if exceeded_any else 0.0)
    except Exception:
        pass

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

    base = metrics.export()
    payload = base.rstrip() + ("\n" if base and not base.endswith("\n") else "") + "\n".join(extra) + "\n"
    return PlainTextResponse(payload, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/config")
def config_public() -> JSONResponse:
    return JSONResponse(_safe_config(CFG))


@app.get("/config/validate")
def config_validate() -> JSONResponse:
    try:
        report = validate_config(CFG, http=HTTP, conn=CONN, bus=BUS, breaker=BREAKER)
        code = 200 if report.get("ok") else 422
        return JSONResponse(report, status_code=code)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.post("/tick")
def tick(body: Dict[str, Any] = Body(default=None)) -> JSONResponse:
    sym = normalize_symbol((body or {}).get("symbol") or getattr(CFG, "SYMBOL", "BTC/USDT"))
    tf = normalize_timeframe((body or {}).get("timeframe") or getattr(CFG, "TIMEFRAME", "1h"))
    limit = int((body or {}).get("limit") or getattr(CFG, "LIMIT_BARS", 300))
    try:
        decision = uc_eval_and_execute(CFG, BROKER, REPOS, symbol=sym, timeframe=tf, limit=limit, bus=BUS, http=HTTP)
        return JSONResponse({"status": "ok" if decision.get("status") == "ok" else decision.get("status"), **decision, "symbol": sym, "timeframe": tf})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"})


@app.get("/bus/health")
def bus_health() -> JSONResponse:
    try:
        return JSONResponse({"status": "ok", "bus": BUS.health()})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"{type(e).__name__}: {e}"})


@app.get("/bus/dlq")
def bus_dlq(limit: int = Query(50, ge=1, le=1000)) -> JSONResponse:
    try:
        items = BUS.dlq_dump(limit=limit)
    except AttributeError:
        items = []
    return JSONResponse({"status": "ok", "items": items})

@app.get("/bus/stats")
def bus_stats(since_ms: Optional[int] = Query(None, description="Фильтр по времени (UTC ms)")) -> JSONResponse:
    try:
        rep = REPOS.journal.stats(since_ms=since_ms)
        h = BUS.health()
        return JSONResponse({"status": "ok", "journal": rep, "bus": h})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"{type(e).__name__}: {e}"}, status_code=500)

# --------- Новые графики (SVG) ----------
@app.get("/chart/test")
def chart_test(
    symbol: Optional[str] = Query(None),
    timeframe: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=2, le=5000),
) -> Response:
    sym = normalize_symbol(symbol or getattr(CFG, "SYMBOL", "BTC/USDT"))
    tf = normalize_timeframe(timeframe or getattr(CFG, "TIMEFRAME", "1h"))
    n = int(limit or getattr(CFG, "LIMIT_BARS", 300))
    try:
        ohlcv = BREAKER.call(lambda: BROKER.fetch_ohlcv(sym, tf, n), key="broker.fetch_ohlcv", timeout=5.0)
        closes = [float(x[4]) for x in ohlcv if x and len(x) >= 5]
    except Exception:
        closes = []
    svg = render_price_spark_svg(closes, title=f"{sym} {tf}")
    return Response(content=svg, media_type="image/svg+xml")

@app.get("/chart/profit")
def chart_profit(
    symbol: Optional[str] = Query(None),
    window: Optional[int] = Query(100, ge=2, le=2000),
) -> Response:
    sym = normalize_symbol(symbol or getattr(CFG, "SYMBOL", "BTC/USDT"))
    pnls: List[float] = []
    try:
        if hasattr(REPOS.trades, "last_closed_pnls"):
            pnls = [float(x) for x in REPOS.trades.last_closed_pnls(int(window or 100)) if x is not None]  # type: ignore
    except Exception:
        pnls = []
    svg = render_profit_curve_svg(pnls, title=f"PnL {sym}")
    return Response(content=svg, media_type="image/svg+xml")
# ----------------------------------------

@app.get("/context")
def get_market_context() -> JSONResponse:
    try:
        ctx = build_market_context(CFG, HTTP, BREAKER)
        return JSONResponse({"status": "ok", "context": ctx})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.get("/status/extended")
def status_extended() -> JSONResponse:
    sym = getattr(CFG, "SYMBOL", "BTC/USDT")
    tf = getattr(CFG, "TIMEFRAME", "1h")

    snap = snapshot_quantiles()

    key_dec = f"decision:{sym}:{tf}"
    key_flow = f"flow:{sym}:{tf}"
    key_ord_buy = f"order:{sym}:{tf}:buy"
    key_ord_sell = f"order:{sym}:{tf}:sell"

    def _pp(k, p):
        try:
            v = snap.get(k, {}).get(p)
            return float(v) if v is not None else None
        except Exception:
            return None

    dec_p95, dec_p99 = _pp(key_dec, "p95"), _pp(key_dec, "p99")
    flow_p95, flow_p99 = _pp(key_flow, "p95"), _pp(key_flow, "p99")
    ord_p95 = max([x for x in (_pp(key_ord_buy, "p95"), _pp(key_ord_sell, "p95")) if x is not None], default=None)
    ord_p99 = max([x for x in (_pp(key_ord_buy, "p99"), _pp(key_ord_sell, "p99")) if x is not None], default=None)

    b_dec = int(getattr(CFG, "PERF_BUDGET_DECISION_P99_MS", 0) or 0)
    b_ord = int(getattr(CFG, "PERF_BUDGET_ORDER_P99_MS", 0) or 0)
    b_flow = int(getattr(CFG, "PERF_BUDGET_FLOW_P99_MS", 0) or 0)

    def _exceeded(v, b):
        if v is None or not b:
            return None
        return float(v) > float(b)

    try:
        open_count = len(REPOS.positions.get_open() or [])
    except Exception:
        open_count = None

    context = build_market_context(CFG, HTTP, BREAKER)

    return JSONResponse({
        "mode": getattr(CFG, "MODE", "unknown"),
        "symbol": sym,
        "timeframe": tf,
        "positions": {"open_count": open_count},
        "quantiles_ms": {
            "decision": {"p95": dec_p95, "p99": dec_p99},
            "order": {"p95": ord_p95, "p99": ord_p99},
            "flow": {"p95": flow_p95, "p99": flow_p99},
        },
        "budgets_ms": {
            "decision_p99": b_dec,
            "order_p99": b_ord,
            "flow_p99": b_flow,
            "decision_p99_exceeded": _exceeded(dec_p99, b_dec),
            "order_p99_exceeded": _exceeded(ord_p99, b_ord),
            "flow_p99_exceeded": _exceeded(flow_p99, b_flow),
        },
        "context": context,
    })


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

    resp = tg_adapter.handle_update(update, CFG, BROKER, HTTP, bus=BUS, repos=REPOS)
    return JSONResponse(resp)
