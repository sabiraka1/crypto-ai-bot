# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
import json
import os
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

from crypto_ai_bot.app.adapters import telegram as tg_adapter

from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe

from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate

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

# Контекст рынка
try:
    from crypto_ai_bot.market_context.snapshot import build_snapshot as build_ctx_snapshot
except Exception:
    build_ctx_snapshot = None  # type: ignore

# Квантили/шина
try:
    from crypto_ai_bot.app.bus_wiring import make_bus, snapshot_quantiles
except Exception:
    # Фоллбеки на случай отсутствия модуля
    class _DummyBus:
        def publish(self, event: Dict[str, Any]) -> None: ...
        def subscribe(self, type_: str, handler) -> None: ...
        def health(self) -> Dict[str, Any]:
            return {"dlq_size": 0, "status": "ok"}
    def make_bus():
        return _DummyBus()
    def snapshot_quantiles():
        return {}

# Валидация конфига
try:
    from crypto_ai_bot.core.validators import validate_config
except Exception:
    def validate_config(*args, **kwargs):
        return {"ok": True, "checks": {"stub": {"status": "warn", "code": "validator_missing"}}}


# =========================
# Инициализация приложения
# =========================

app = FastAPI(title="crypto-ai-bot")

CFG = Settings.build()
init_logging(level=CFG.LOG_LEVEL, json_format=getattr(CFG, "LOG_JSON", False))

HTTP = get_http_client()
BREAKER = CircuitBreaker()

# Хранилище
CONN = connect(CFG.DB_PATH)

class _Repos:
    def __init__(self, con):
        self.positions = SqlitePositionRepository(con)
        self.trades = SqliteTradeRepository(con)
        self.audit = SqliteAuditRepository(con)
        self.idempotency = SqliteIdempotencyRepository(con)
        self.uow = SqliteUnitOfWork(con)
        self.decisions = SqliteDecisionsRepository(con) if SqliteDecisionsRepository else None

REPOS = _Repos(CONN)

# Шина событий
BUS = make_bus()

# Брокер
BROKER = create_broker(CFG, bus=BUS)

# Сохраним ссылки в CFG (чтобы валидатор и др. могли их увидеть)
try:
    CFG.BROKER = BROKER  # type: ignore[attr-defined]
except Exception:
    pass


# ==============
# Эндпоинты
# ==============

@app.get("/health")
def health() -> JSONResponse:
    # лёгкая проверка основных зависимостей
    try:
        db_ok = True
        CONN.execute("SELECT 1")
    except Exception:
        db_ok = False

    try:
        b = BROKER.fetch_ticker(CFG.SYMBOL)
        broker_ok = bool(b)
    except Exception:
        broker_ok = False

    try:
        bus_h = BUS.health()
        dlq = int(bus_h.get("dlq_size") or bus_h.get("dlq_len") or 0)
    except Exception:
        dlq = 0

    status = "healthy"
    if not db_ok or not broker_ok:
        status = "unhealthy"
    elif dlq > 0:
        status = "degraded"

    return JSONResponse({
        "status": status,
        "db": db_ok,
        "broker": broker_ok,
        "dlq": dlq,
        "mode": CFG.MODE,
        "symbol": CFG.SYMBOL,
        "timeframe": CFG.TIMEFRAME,
    })


@app.get("/config/validate")
def config_validate() -> JSONResponse:
    rep = validate_config(CFG, http=HTTP, conn=CONN, bus=BUS, breaker=BREAKER)
    return JSONResponse(rep)


@app.get("/bus/health")
def bus_health() -> JSONResponse:
    try:
        return JSONResponse(BUS.health())
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"{type(e).__name__}: {e}"})


@app.get("/bus/dlq")
def bus_dlq() -> JSONResponse:
    try:
        h = BUS.health()
        return JSONResponse({"dlq_size": int(h.get("dlq_size") or h.get("dlq_len") or 0)})
    except Exception:
        return JSONResponse({"dlq_size": 0})


@app.get("/context")
def context_snapshot() -> JSONResponse:
    if not build_ctx_snapshot:
        return JSONResponse({"status": "disabled"})
    try:
        snap = build_ctx_snapshot(CFG, HTTP, BREAKER)
        return JSONResponse(snap)
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"{type(e).__name__}: {e}"})


@app.get("/status/extended")
def status_extended() -> JSONResponse:
    # базовые сведения
    resp: Dict[str, Any] = {
        "mode": CFG.MODE,
        "symbol": CFG.SYMBOL,
        "timeframe": CFG.TIMEFRAME,
        "rl": {
            "evaluate_per_min": getattr(CFG, "RL_EVALUATE_PER_MIN", 60),
            "orders_per_min": getattr(CFG, "RL_ORDERS_PER_MIN", 10),
        },
        "perf_budgets_ms": {
            "decision": getattr(CFG, "PERF_BUDGET_DECISION_P99_MS", 0),
            "order": getattr(CFG, "PERF_BUDGET_ORDER_P99_MS", 0),
            "flow": getattr(CFG, "PERF_BUDGET_FLOW_P99_MS", 0),
        },
    }

    # состояние шины
    try:
        resp["bus"] = BUS.health()
    except Exception:
        resp["bus"] = {"status": "unknown"}

    # квантильные снапшоты
    try:
        resp["quantiles"] = snapshot_quantiles()
    except Exception:
        resp["quantiles"] = {}

    # вложенный market context
    if build_ctx_snapshot:
        try:
            resp["context"] = build_ctx_snapshot(CFG, HTTP, BREAKER)
        except Exception as e:
            resp["context"] = {"status": "error", "error": f"{type(e).__name__}: {e}"}

    return JSONResponse(resp)


@app.get("/metrics")
def metrics_export() -> PlainTextResponse:
    # SQLite метрики
    try:
        _ = sqlite_snapshot(CONN, path_hint=getattr(CFG, "DB_PATH", None))
    except Exception:
        pass

    # Загрузим метрики бэктеста из файла (если есть)
    try:
        metrics_path = getattr(CFG, "BACKTEST_METRICS_PATH", "backtest_metrics.json")
        if metrics_path and os.path.exists(metrics_path):
            with open(metrics_path, "r", encoding="utf-8") as f:
                bt = json.load(f)
            if isinstance(bt, dict):
                if "backtest_trades_total" in bt:
                    metrics.gauge("backtest_trades_total", float(bt["backtest_trades_total"]))
                if "backtest_equity_last" in bt:
                    metrics.gauge("backtest_equity_last", float(bt["backtest_equity_last"]))
                if "backtest_max_drawdown_pct" in bt:
                    metrics.gauge("backtest_max_drawdown_pct", float(bt["backtest_max_drawdown_pct"]))
    except Exception:
        pass

    # DLQ счётчик
    try:
        h = BUS.health()
        dlq = int(h.get("dlq_size") or h.get("dlq_len") or h.get("dlq", 0) or 0)
        metrics.gauge("events_dead_letter_total", float(dlq))
    except Exception:
        metrics.gauge("events_dead_letter_total", 0.0)

    # performance budgets p99 по квантилям
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

    # Состояния CircuitBreaker
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


# ---------- Графики (SVG) ----------

from crypto_ai_bot.utils.charts import render_price_spark_svg, render_profit_curve_svg, closes_from_ohlcv

@app.get("/chart/test")
def chart_test(
    symbol: Optional[str] = Query(None),
    timeframe: Optional[str] = Query(None),
    limit: int = Query(200),
):
    sym = symbol or CFG.SYMBOL
    tf = timeframe or CFG.TIMEFRAME
    try:
        ohlcv = BROKER.fetch_ohlcv(sym, tf, limit=int(limit))
        closes = closes_from_ohlcv(ohlcv)
    except Exception:
        closes = []
    svg = render_price_spark_svg(closes, title=f"{sym} {tf} close")
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/chart/profit")
def chart_profit():
    try:
        if hasattr(REPOS.trades, "last_closed_pnls"):
            pnls = REPOS.trades.last_closed_pnls(10000)  # type: ignore
        else:
            pnls = []
    except Exception:
        pnls = []
    svg = render_profit_curve_svg([float(x) for x in (pnls or []) if x is not None], title="Equity curve")
    return Response(content=svg, media_type="image/svg+xml")


# ---------- Основные действия ----------

@app.post("/tick")
def tick(
    payload: Dict[str, Any] = Body(default=None),
) -> JSONResponse:
    symbol = normalize_symbol((payload or {}).get("symbol") or CFG.SYMBOL)
    timeframe = normalize_timeframe((payload or {}).get("timeframe") or CFG.TIMEFRAME)
    limit = int((payload or {}).get("limit") or getattr(CFG, "LOOKBACK_LIMIT", getattr(CFG, "LIMIT_BARS", 300)))

    with metrics.timer() as t:
        out = uc_eval_and_execute(
            CFG,
            BROKER,
            REPOS,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            bus=BUS,
            http=HTTP,
        )
    metrics.observe_histogram("latency_flow_seconds", t.elapsed, labels={"kind": "tick"})
    metrics.check_performance_budget("flow", t.elapsed, getattr(CFG, "PERF_BUDGET_FLOW_P99_MS", None))

    return JSONResponse(out)


@app.post("/telegram")
async def telegram(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> JSONResponse:
    # Опциональная проверка секрета
    secret = getattr(CFG, "TELEGRAM_WEBHOOK_SECRET", None)
    if secret and x_telegram_bot_api_secret_token != secret:
        return JSONResponse({"status": "forbidden"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        body = {}

    # делегируем адаптеру; если что-то не так — мягко не падаем
    try:
        if hasattr(tg_adapter, "handle"):
            resp = await tg_adapter.handle(body, cfg=CFG, broker=BROKER, repos=REPOS, bus=BUS, http=HTTP)  # type: ignore
        elif hasattr(tg_adapter, "process"):
            resp = await tg_adapter.process(body, cfg=CFG, broker=BROKER, repos=REPOS, bus=BUS, http=HTTP)  # type: ignore
        else:
            resp = {"status": "ok"}
    except Exception as e:
        resp = {"status": "error", "error": f"{type(e).__name__}: {e}"}
    return JSONResponse(resp)


# ---------- Диагностика/отладка ----------

@app.post("/dry/evaluate")
def dry_evaluate(
    symbol: str = Query(None),
    timeframe: str = Query(None),
    limit: int = Query(200),
) -> JSONResponse:
    sym = normalize_symbol(symbol or CFG.SYMBOL)
    tf = normalize_timeframe(timeframe or CFG.TIMEFRAME)
    with metrics.timer() as t:
        d = uc_evaluate(CFG, BROKER, symbol=sym, timeframe=tf, limit=limit)
    metrics.observe_histogram("latency_decision_seconds", t.elapsed, labels={"kind": "evaluate"})
    metrics.check_performance_budget("decision", t.elapsed, getattr(CFG, "PERF_BUDGET_DECISION_P99_MS", None))
    return JSONResponse(d)
