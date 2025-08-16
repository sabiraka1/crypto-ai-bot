# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers import create_broker
from crypto_ai_bot.core.storage import connect, SqliteUnitOfWork
from crypto_ai_bot.core.storage.repositories import (
    SqliteTradeRepository,
    SqlitePositionRepository,
    SqliteSnapshotRepository,
    SqliteAuditRepository,
    SqliteIdempotencyRepository,
)
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order as uc_place_order
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute

from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.utils import metrics

# Телеграм адаптер может быть опционален (например, на ранних этапах)
try:
    from crypto_ai_bot.app.adapters.telegram import handle_update as tg_handle_update
    _HAS_TG = True
except Exception:
    tg_handle_update = None  # type: ignore
    _HAS_TG = False


# ───────────────────────────── инициализация ─────────────────────────────────

cfg = Settings.build()

# гарантируем, что каталог для БД существует
db_path = Path(getattr(cfg, "DB_PATH", "data/bot.db"))
db_path.parent.mkdir(parents=True, exist_ok=True)

con = connect(str(db_path))
uow = SqliteUnitOfWork(con)

repos: Dict[str, Any] = {
    "trades": SqliteTradeRepository(con),
    "positions": SqlitePositionRepository(con),
    "snapshots": SqliteSnapshotRepository(con),
    "audit": SqliteAuditRepository(con),
    "idempotency": SqliteIdempotencyRepository(con),
    "uow": uow,
}

broker = create_broker(cfg)  # фабрика под MODE: live/paper/backtest
http = get_http_client()     # единый HTTP клиент для «внешних» интеграций (бот-API и т.п.)

app = FastAPI(title="Crypto AI Bot", version=getattr(cfg, "APP_VERSION", "0.1.0"))


# ───────────────────────────── служебные штуки ────────────────────────────────

def _component_health() -> Dict[str, Any]:
    """
    Возвращает статус внутренних компонент.
    Никаких блокирующих долгих операций.
    """
    status = {"db": "unknown", "broker": "unknown", "mode": cfg.MODE}

    # DB ping
    try:
        con.execute("SELECT 1;")
        status["db"] = "ok"
    except Exception as e:
        status["db"] = f"error: {type(e).__name__}"

    # Broker ping (коротко: только попытка получить тикер)
    try:
        _ = broker.fetch_ticker(cfg.SYMBOL)
        status["broker"] = "ok"
    except Exception as e:
        status["broker"] = f"error: {type(e).__name__}"

    return status


def _overall_status(components: Dict[str, str]) -> str:
    if all(v == "ok" for v in components.values() if v not in ("mode",)):
        return "healthy"
    if any(str(v).startswith("error") for v in components.values()):
        return "degraded"
    return "unknown"


# ───────────────────────────── маршруты ──────────────────────────────────────

@app.get("/health")
def health() -> JSONResponse:
    t0 = time.perf_counter()
    comp = _component_health()
    overall = _overall_status(comp)
    metrics.observe("health_check_duration_seconds", time.perf_counter() - t0, {"status": overall})
    payload = {
        "status": overall,
        "components": comp,
        "symbol": cfg.SYMBOL,
        "timeframe": cfg.TIMEFRAME,
        "mode": cfg.MODE,
        "version": getattr(cfg, "APP_VERSION", "0.1.0"),
    }
    return JSONResponse(payload)


@app.get("/metrics")
def metrics_export() -> Response:
    text = metrics.export()
    # стандартный content-type для Prometheus text exposition format
    return PlainTextResponse(
        text,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.post("/telegram")
async def telegram_webhook(request: Request) -> JSONResponse:
    if not _HAS_TG or tg_handle_update is None:
        raise HTTPException(status_code=501, detail="telegram adapter not installed")

    # Базовая защита: секрет заголовка Telegram (если сконфигурирован)
    secret = getattr(cfg, "TELEGRAM_WEBHOOK_SECRET", None)
    if secret:
        recv = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if recv != secret:
            raise HTTPException(status_code=403, detail="forbidden")

    raw = await request.body()
    try:
        update = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        update = {}

    # Передаём всё в адаптер — без бизнес-логики
    try:
        result = await tg_handle_update(update, cfg, broker, http)  # тонкий адаптер
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    return JSONResponse(result or {"ok": True})


@app.post("/tick")
def tick() -> JSONResponse:
    """
    Явный однократный шаг цикла (удобно для smoke-тестов и crontab).
    Конвейер: evaluate → risk (внутри) → place_order (атомарно).
    """
    try:
        res = uc_eval_and_execute(
            cfg,
            broker,
            symbol=cfg.SYMBOL,
            timeframe=cfg.TIMEFRAME,
            limit=int(getattr(cfg, "FEATURE_LIMIT", 300)),
            repos=repos,
        )
        return JSONResponse({"ok": True, "result": res})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ───────────────────────────── lifecycle hooks ────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    metrics.inc("app_start_total", {"mode": cfg.MODE})


@app.on_event("shutdown")
async def on_shutdown() -> None:
    metrics.inc("app_stop_total", {"mode": cfg.MODE})
    # закрывать соединение sqlite не обязательно, но можно:
    try:
        con.close()
    except Exception:
        pass
