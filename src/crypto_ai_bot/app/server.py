
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.bot import Bot
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.utils import metrics


app = FastAPI(title="crypto-ai-bot")

# Глобальные синглтоны на процесс
CFG: Optional[Settings] = None
BOT: Optional[Bot] = None


def _measure_db_latency(db_path: str) -> tuple[str, int]:
    try:
        t0 = time.perf_counter_ns()
        con = connect(db_path)
        con.execute("SELECT 1").fetchone()
        lat_ms = int((time.perf_counter_ns() - t0) / 1_000_000)
        return "ok", lat_ms
    except Exception as e:  # pragma: no cover
        return f"error:{type(e).__name__}", 0


def _measure_broker_latency(bot: Bot, symbol: str) -> tuple[str, int]:
    try:
        t0 = time.perf_counter_ns()
        # безопасный вызов тикера
        bot.broker.fetch_ticker(symbol)
        lat_ms = int((time.perf_counter_ns() - t0) / 1_000_000)
        return "ok", lat_ms
    except Exception as e:  # pragma: no cover
        return f"error:{type(e).__name__}", 0


def _measure_time_drift_limit(cfg: Settings) -> tuple[str, int, int]:
    # Заглушка: локально считаем drift == 0, лимит берём из настроек
    limit_ms = int(getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1500))
    return "ok", 0, limit_ms


@app.on_event("startup")
def on_startup() -> None:
    global CFG, BOT
    CFG = Settings.build()
    BOT = Bot(CFG)
    metrics.inc("app_start_total", {"mode": "paper" if CFG.PAPER_MODE else "live"})


@app.get("/health")
def health() -> JSONResponse:
    assert CFG and BOT
    comp: Dict[str, Any] = {"mode": "paper" if CFG.PAPER_MODE else "live"}

    db_status, db_lat = _measure_db_latency(CFG.DB_PATH)
    comp["db"] = {"status": db_status, "latency_ms": db_lat}

    br_status, br_lat = _measure_broker_latency(BOT, CFG.SYMBOL)
    comp["broker"] = {"status": br_status, "latency_ms": br_lat}

    t_status, drift_ms, limit_ms = _measure_time_drift_limit(CFG)
    comp["time"] = {"status": t_status, "drift_ms": drift_ms, "limit_ms": limit_ms}

    # матрица статусов
    errors = [v for v in (db_status, br_status, t_status) if v.startswith("error")]
    degraded = (
        (db_lat > 250)
        or (br_lat > 2500)
        or (drift_ms > limit_ms)
    )

    if errors:
        status = "unhealthy"
        level = "critical"
    elif degraded:
        status = "degraded"
        level = "major"
    else:
        status = "healthy"
        level = "none"

    body = {"status": status, "degradation_level": level, "components": comp}
    return JSONResponse(body)


@app.get("/metrics")
def metrics_endpoint() -> PlainTextResponse:
    return PlainTextResponse(metrics.export(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.post("/tick")
async def tick(req: Request) -> JSONResponse:
    assert CFG and BOT
    payload = await req.json() if req.headers.get("content-type","").startswith("application/json") else {}
    symbol = payload.get("symbol")
    timeframe = payload.get("timeframe")
    limit = payload.get("limit")

    execute = bool(payload.get("execute", False))
    try:
        if execute:
            res = BOT.eval_and_execute(symbol=symbol, timeframe=timeframe, limit=limit)
            return JSONResponse({"status": "executed", **res})
        else:
            dec = BOT.evaluate(symbol=symbol, timeframe=timeframe, limit=limit)
            return JSONResponse({"status": "evaluated", "symbol": symbol or CFG.SYMBOL, "timeframe": timeframe or CFG.TIMEFRAME, "decision": dec})
    except Exception as e:  # pragma: no cover
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"})


@app.post("/telegram")
async def telegram(req: Request, x_telegram_bot_api_secret_token: Optional[str] = Header(default=None)) -> JSONResponse:
    assert CFG and BOT
    # при желании можно включить проверку секрета:
    secret = getattr(CFG, "TELEGRAM_WEBHOOK_SECRET", None)
    if secret:
        if x_telegram_bot_api_secret_token != secret:
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    body = await req.json()
    # ленивый импорт, чтобы не тянуть зависимость в /tick
    from crypto_ai_bot.app.adapters.telegram import handle_update  # type: ignore

    # http-клиент для ответов в Telegram (если нужен)
    class _DummyHttp:
        def post_json(self, *args, **kwargs):  # pragma: no cover - опционально
            return {"ok": True}

    res = await handle_update(body, CFG, BOT, _DummyHttp())
    return JSONResponse(res)
