from __future__ import annotations

import asyncio
from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse, JSONResponse

from ..core.settings import Settings
from .compose import build_container

# отчёт метрик (JSON fallback), если модуль есть
try:
    from ..core.analytics.metrics import report_dict as metrics_report_dict
except Exception:
    metrics_report_dict = None

# безопасный импорт метрик как модуля (без именованных символов)
from ..utils import metrics as _metrics

app = FastAPI(title="crypto-ai-bot")
app.state.container = build_container()

# --- LIVENESS ожидается тестами ---
@app.get("/live")
async def live() -> dict:
    return {"ok": True}

@app.get("/ready")
async def ready() -> dict:
    c = app.state.container
    return {"ok": c is not None and c.broker is not None}

@app.get("/health")
async def health() -> dict:
    """
    Возвращаем:
      - ok: bool
      - components: dict (минимум bus/broker/storage/db)
      - ts_ms: int
      - а также плоские *_ok флаги на верхнем уровне (напр. db_ok), т.к. этого ждут тесты.
    """
    c = app.state.container
    rep = await c.health.check(symbol=c.settings.SYMBOL)

    # извлечь ok/ts_ms/components из объекта или dict
    if isinstance(rep, dict):
        ok = bool(rep.get("ok", True))
        ts_ms = rep.get("ts_ms", 0)
        components = rep.get("components")
    else:
        ok = getattr(rep, "ok", True)
        ts_ms = getattr(rep, "ts_ms", 0)
        components = getattr(rep, "components", None)

    # если components отсутствуют — собрать минимум
    if components is None:
        components = {}
        try:
            src = rep if isinstance(rep, dict) else getattr(rep, "__dict__", {})
            if isinstance(src, dict):
                for k, v in src.items():
                    if k.endswith("_ok") and isinstance(v, bool):
                        components[k[:-3]] = v
        except Exception:
            pass
        components.setdefault("bus", c.bus is not None)
        components.setdefault("broker", c.broker is not None)
        # пробуем разные ключи для БД
        components.setdefault("db", getattr(c.storage, "conn", None) is not None or getattr(c.storage, "db", None) is not None)
        components.setdefault("storage", c.storage is not None)

    # дополнительный быстрый live-пинг брокера
    live_ok = True
    live_error = ""
    if c.settings.MODE == "live":
        try:
            await asyncio.wait_for(c.broker.fetch_balance(), timeout=1.0)
        except Exception as exc:
            live_ok = False
            live_error = str(exc)
        ok = bool(ok and live_ok)
        components["live_broker"] = live_ok

    # формируем итог
    res = {
        "ok": bool(ok),
        "components": components,
        "ts_ms": int(ts_ms) if isinstance(ts_ms, (int, float)) else 0,
    }
    # плоские *_ok флаги на верхнем уровне (важно для тестов: нужен db_ok)
    for name, val in components.items():
        if isinstance(val, bool):
            res[f"{name}_ok"] = val
    if c.settings.MODE == "live" and not live_ok and live_error:
        res["error"] = live_error
    return res

@app.get("/metrics")
async def metrics() -> Response:
    """
    1) Если есть функция prom-текста — используем её.
    2) Иначе — JSON снимок in-memory.
    3) Иначе — core.analytics.metrics.report_dict(), если доступен.
    """
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
