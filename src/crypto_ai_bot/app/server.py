from __future__ import annotations

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse, JSONResponse

from ..core.settings import Settings
from .compose import build_container
from ..utils.time import now_ms  # ✅ Добавлен импорт

# отчёт метрик (JSON fallback), если модуль есть
try:
    from ..core.analytics.metrics import report_dict as metrics_report_dict
except Exception:
    metrics_report_dict = None

# безопасный импорт метрик как модуля (без именованных символов)
from ..utils import metrics as _metrics

app = FastAPI(title="crypto-ai-bot")
app.state.container = build_container()


@app.get("/health")
async def health() -> dict:
    c = app.state.container
    rep = await c.health.check(symbol=c.settings.SYMBOL)
    # ✅ Используем now_ms() если ts_ms недоступен
    ts = getattr(rep, 'ts_ms', now_ms())
    # ✅ Возвращаем все поля HealthReport в корне
    return {
        "ok": rep.ok,
        "db_ok": rep.db_ok,
        "migrations_ok": rep.migrations_ok,
        "broker_ok": rep.broker_ok,
        "bus_ok": rep.bus_ok,
        "clock_drift_ms": rep.clock_drift_ms,
        "details": rep.details,
        "ts_ms": ts
    }


@app.get("/ready")
async def ready() -> dict:
    c = app.state.container
    return {"ok": c is not None and c.broker is not None}


@app.get("/live")
async def live() -> dict:
    """Liveness probe endpoint - проверяет что приложение живо"""
    c = app.state.container
    return {"ok": c is not None and c.broker is not None}


@app.get("/metrics")
async def metrics() -> Response:
    """
    1) Если есть функция prom-текста (prometheus_text|render_prometheus|export_prometheus) — используем её.
    2) Иначе, если есть snapshot() — отдаём JSON снимок (in-memory).
    3) Иначе — core.analytics.metrics.report_dict(), если доступен.
    """
    # Пытаемся найти подходящую функцию Prometheus-текста
    prom_fn = None
    for name in ("prometheus_text", "render_prometheus", "export_prometheus"):
        f = getattr(_metrics, name, None)
        if callable(f):
            prom_fn = f
            break

    if prom_fn:
        try:
            text = prom_fn()
            if isinstance(text, str) and text.strip():
                return PlainTextResponse(text, media_type="text/plain; version=0.0.4")
        except Exception:
            pass

    snap_fn = getattr(_metrics, "snapshot", None)
    if callable(snap_fn):
        try:
            return JSONResponse(snap_fn())
        except Exception:
            pass

    if metrics_report_dict:
        try:
            return JSONResponse(metrics_report_dict())
        except Exception:
            pass

    # на самый крайний случай — пустой объект
    return JSONResponse({})


@app.get("/status")
async def status() -> dict:
    c = app.state.container
    s = c.settings
    bus_q = c.bus.qsize()
    cfg = c.risk._cfg
    orch = c.orchestrator.status()
    return {
        "ok": True,
        "mode": s.MODE,
        "exchange": s.EXCHANGE,
        "symbol": s.SYMBOL,
        "risk": {
            "cooldown_sec": cfg.cooldown_sec,
            "max_spread_pct": cfg.max_spread_pct,
            "max_position_base": str(cfg.max_position_base) if cfg.max_position_base is not None else None,
            "max_orders_per_hour": cfg.max_orders_per_hour,
            "daily_loss_limit_quote": str(cfg.daily_loss_limit_quote) if cfg.daily_loss_limit_quote is not None else None,
        },
        "bus": {"qsize": bus_q},
        "orchestrator": orch,
    }


@app.post("/orchestrator/start")
async def orchestrator_start() -> dict:
    c = app.state.container
    c.orchestrator.start()
    return {"ok": True, "status": c.orchestrator.status()}


@app.post("/orchestrator/stop")
async def orchestrator_stop() -> dict:
    c = app.state.container
    await c.orchestrator.stop()
    return {"ok": True, "status": c.orchestrator.status()}


@app.get("/orchestrator/status")
async def orchestrator_status() -> dict:
    c = app.state.container
    return {"ok": True, "status": c.orchestrator.status()}