from __future__ import annotations
import os, time, json, pathlib
from typing import Any, Dict

from fastapi import FastAPI, Body, Request, Header
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute
from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.get_stats import get_stats as uc_get_stats
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.uow import SqliteUnitOfWork
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
from crypto_ai_bot.utils.metrics import export as metrics_export, inc, observe
from crypto_ai_bot.utils import http_client
from crypto_ai_bot.app.adapters.telegram import handle_update

try:
    from crypto_ai_bot.core.brokers.base import create_broker
except Exception:
    create_broker = None  # type: ignore

app = FastAPI(title="crypto-ai-bot")

CFG = Settings.build()

# prepare storage if path given
CON = None
if CFG.DB_PATH:
    pathlib.Path(CFG.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    try:
        CON = connect(CFG.DB_PATH)
    except Exception:
        CON = None

BROKER = None
if create_broker:
    try:
        BROKER = create_broker(CFG.MODE, CFG)  # type: ignore
    except Exception:
        BROKER = None

@app.get("/health")
def health() -> JSONResponse:
    status = "healthy"
    comp: Dict[str, Any] = {"mode": CFG.MODE}
    # db
    t0 = time.time()
    try:
        if CON is None:
            raise RuntimeError("no_db")
        CON.execute("SELECT 1;").fetchone()
        db_lat = int((time.time()-t0)*1000)
        comp["db"] = {"status": "ok", "latency_ms": db_lat}
    except Exception as e:
        comp["db"] = {"status": f"error:{type(e).__name__}"}
        status = "degraded"

    # broker
    t0 = time.time()
    try:
        if BROKER is None:
            raise RuntimeError("no_broker")
        _ = BROKER.fetch_ticker(CFG.SYMBOL)
        bk_lat = int((time.time()-t0)*1000)
        comp["broker"] = {"status": "ok", "latency_ms": bk_lat}
    except Exception as e:
        comp["broker"] = {"status": f"error:{type(e).__name__}"}
        status = "degraded"

    # time drift
    try:
        from crypto_ai_bot.utils.time_sync import get_cached_drift_ms
        drift = int(get_cached_drift_ms(0))
        comp["time"] = {"status": "ok", "drift_ms": drift, "limit_ms": CFG.TIME_DRIFT_MAX_MS}
        if drift > CFG.TIME_DRIFT_MAX_MS:
            status = "degraded"
    except Exception as e:
        comp["time"] = {"status": f"error:{type(e).__name__}"}

    # degradation level
    degr = "none" if status == "healthy" else "major"
    return JSONResponse({"status": status, "degradation_level": degr, "components": comp})

@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(metrics_export(), media_type="text/plain; version=0.0.4; charset=utf-8")

@app.post("/tick")
def tick(payload: Dict[str, Any] = Body(default={})):
    symbol = payload.get("symbol", CFG.SYMBOL)
    timeframe = payload.get("timeframe", CFG.TIMEFRAME)
    limit = int(payload.get("limit", 300))

    positions_repo = trades_repo = audit_repo = uow = idem_repo = None
    if CON is not None and CFG.ENABLE_TRADING:
        positions_repo = SqlitePositionRepository(CON)
        trades_repo = SqliteTradeRepository(CON)
        audit_repo = SqliteAuditRepository(CON)
        uow = SqliteUnitOfWork(CON)
        idem_repo = SqliteIdempotencyRepository(CON)

    try:
        res = uc_eval_and_execute(
            CFG, BROKER, symbol=symbol, timeframe=timeframe, limit=limit,
            positions_repo=positions_repo, trades_repo=trades_repo, audit_repo=audit_repo, uow=uow, idempotency_repo=idem_repo,
        )
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"})

@app.get("/debug/why")
def debug_why(symbol: str | None = None, timeframe: str | None = None, limit: int = 300):
    if CFG.MODE == "live":
        return JSONResponse({"error": "forbidden_in_live"}, status_code=403)
    try:
        d = uc_evaluate(CFG, BROKER, symbol=symbol or CFG.SYMBOL, timeframe=timeframe or CFG.TIMEFRAME, limit=limit)
        return JSONResponse(d)
    except Exception as e:
        return JSONResponse({"error": f"debug_why_failed: {type(e).__name__}: {e}"}, status_code=500)

@app.get("/stats")
def stats():
    # подключаем репозитории только если есть соединение (даже при ENABLE_TRADING=false — чтение безопасно)
    positions_repo = trades_repo = None
    try:
        if CON is not None:
            positions_repo = SqlitePositionRepository(CON)
            trades_repo = SqliteTradeRepository(CON)
    except Exception:
        positions_repo = trades_repo = None
    try:
        res = uc_get_stats(CFG, BROKER, positions_repo=positions_repo, trades_repo=trades_repo)
        return JSONResponse({"status": "ok", "stats": res, "storage": CON is not None})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"stats_failed: {type(e).__name__}: {e}"} , status_code=200)

@app.post("/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
):
    expected = CFG.TELEGRAM_SECRET_TOKEN
    if not expected or x_telegram_bot_api_secret_token != expected:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    update = await request.json()
    http = http_client.get_http_client()

    try:
        msg = await handle_update(update, CFG, BROKER, http)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"handle_update_failed:{type(e).__name__}:{e}"}, status_code=200)

    token = CFG.TELEGRAM_BOT_TOKEN
    if not token:
        return JSONResponse({"ok": False, "error": "TELEGRAM_BOT_TOKEN not set", "reply": msg}, status_code=200)

    try:
        chat_id = msg.get("chat_id")
        text = msg.get("text", "")
        http.post_json(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=5.0)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"telegram_send_failed:{type(e).__name__}:{e}", "reply": msg}, status_code=200)

    return JSONResponse({"ok": True, "reply": msg}, status_code=200)
