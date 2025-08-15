# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CollectorRegistry, Gauge, generate_latest, CONTENT_TYPE_LATEST

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.telegram.handler import (
    validate_secret_header,
    dispatch_update,
    set_webhook,
    delete_webhook,
    get_webhook_info,
)
# Ğ½ĞµĞ¾Ğ±ÑĞ·Ğ°Ñ‚ĞµĞ»ÑŒĞ½Ğ¾, Ğ½Ğ¾ ĞµÑĞ»Ğ¸ ĞµÑÑ‚ÑŒ â€” ÑƒĞ´Ğ¾Ğ±Ğ½Ğ¾ Ğ¿ĞµÑ€ĞµĞ´Ğ°Ñ‚ÑŒ notifier
try:
    from crypto_ai_bot.telegram.bot import send_telegram_message  # Ñ‚Ğ¾Ğ½ĞºĞ¸Ğ¹ Ğ°Ğ´Ğ°Ğ¿Ñ‚ĞµÑ€ (Ğ¾Ğ±Ñ‘Ñ€Ñ‚ĞºĞ° Ğ½Ğ°Ğ´ send_text)
except Exception:  # pragma: no cover
    def send_telegram_message(text: str) -> bool:  # type: ignore[no-redef]
        logging.getLogger(__name__).warning("send_telegram_message shim used; telegram.bot not ready")
        return False

# ĞµÑĞ»Ğ¸ ĞµÑÑ‚ÑŒ ÑĞ´Ñ€Ğ¾ â€” Ğ¿Ğ¾Ğ´Ñ…Ğ²Ğ°Ñ‚Ğ¸Ğ¼ ĞµĞ´Ğ¸Ğ½ÑÑ‚Ğ²ĞµĞ½Ğ½Ñ‹Ğ¹ Ğ±Ğ¾Ñ‚
try:
    from crypto_ai_bot.core.bot import get_bot  # type: ignore
except Exception:  # pragma: no cover
    def get_bot(*args, **kwargs):  # type: ignore[no-redef]
        logging.getLogger(__name__).warning("core.bot.get_bot not found â€” running without trading engine")
        return None


logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

app = FastAPI(title="Crypto AI Bot API", version="1.0.0")

# --- Prometheus ---------------------------------------------------------------
_registry = CollectorRegistry()
_g_app_info = Gauge("app_info", "App info", ["version"], registry=_registry)
_g_uptime = Gauge("app_uptime_seconds", "App uptime seconds", registry=_registry)
_start_ts = time.time()
_g_app_info.labels(version="1.0.0").set(1.0)


@app.middleware("http")
async def _uptime(_request: Request, call_next):
    _g_uptime.set(time.time() - _start_ts)
    return await call_next(_request)


# --- Startup: Settings + Webhook + Bot ---------------------------------------
@app.on_event("startup")
def on_startup() -> None:
    cfg = Settings.build()
    logger.info("Startup with SYMBOL=%s TIMEFRAME=%s", cfg.SYMBOL, cfg.TIMEFRAME)

    # 1) auto-webhook (ĞµÑĞ»Ğ¸ Ğ²ĞºĞ»ÑÑ‡ĞµĞ½Ğ¾ Ğ¿ĞµÑ€ĞµĞ¼ĞµĞ½Ğ½Ğ¾Ğ¹)
    if str(os.getenv("ENABLE_WEBHOOK", "0")).strip() in ("1", "true", "True"):
        public_url = cfg.PUBLIC_URL or os.getenv("PUBLIC_URL")
        if not public_url:
            logger.warning("ENABLE_WEBHOOK=1, Ğ½Ğ¾ PUBLIC_URL Ğ½Ğµ Ğ·Ğ°Ğ´Ğ°Ğ½ â€” Ğ¿Ñ€Ğ¾Ğ¿ÑƒÑĞºĞ°Ñ setWebhook")
        else:
            wh_url = public_url.rstrip("/") + "/telegram"
            ok, resp = set_webhook(
                bot_token=cfg.BOT_TOKEN,
                webhook_url=wh_url,
                secret_token=cfg.TELEGRAM_SECRET_TOKEN or "",
                drop_pending=True,
            )
            logger.info("setWebhook(%s) â†’ ok=%s resp=%s", wh_url, ok, resp)

            ok_i, info = get_webhook_info(cfg.BOT_TOKEN)
            logger.info("getWebhookInfo â†’ ok=%s info=%s", ok_i, info)

    # 2) ĞµĞ´Ğ¸Ğ½Ñ‹Ğ¹ Ğ±Ğ¾Ñ‚ (Ğ¿Ğ¾ Ğ²Ğ¾Ğ·Ğ¼Ğ¾Ğ¶Ğ½Ğ¾ÑÑ‚Ğ¸)
    try:
        get_bot(notifier=send_telegram_message, settings=cfg)
        logger.info("Trading bot is initialized (singleton).")
    except Exception:
        logger.exception("Trading bot init failed â€” Ğ¿Ñ€Ğ¾Ğ´Ğ¾Ğ»Ğ¶Ğ°Ñ Ğ±ĞµĞ· Ğ½ĞµĞ³Ğ¾ (API Ğ¶Ğ¸Ğ²).")


# --- Health / Metrics ---------------------------------------------------------
@app.get("/healthz", summary="K8s/railway probe")
def healthz() -> Dict[str, Any]:
    return {"ok": True, "uptime": int(time.time() - _start_ts)}

@app.get("/metrics")
def metrics() -> Response:
    return Response(
        generate_latest(_registry),
        media_type=CONTENT_TYPE_LATEST,
    )


# --- Runtime config snapshot (Ğ±ĞµĞ· ÑĞµĞºÑ€ĞµÑ‚Ğ¾Ğ²) -----------------------------------
@app.get("/config", summary="Runtime settings (safe snapshot)")
def config_snapshot() -> Dict[str, Any]:
    cfg = Settings.build()
    safe = {
        "SYMBOL": cfg.SYMBOL,
        "TIMEFRAME": cfg.TIMEFRAME,
        "AGGREGATOR_LIMIT": cfg.AGGREGATOR_LIMIT,
        "ANALYSIS_INTERVAL": cfg.ANALYSIS_INTERVAL,
        "ENABLE_TRADING": cfg.ENABLE_TRADING,
        "SAFE_MODE": cfg.SAFE_MODE,
        "PAPER_MODE": cfg.PAPER_MODE,
        "TRADE_AMOUNT": cfg.TRADE_AMOUNT,
        "MAX_CONCURRENT_POS": cfg.MAX_CONCURRENT_POS,
        "OHLCV_LIMIT": cfg.OHLCV_LIMIT,
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
        "PUBLIC_URL": (Settings.build().PUBLIC_URL or os.getenv("PUBLIC_URL") or ""),
        "WEBHOOK_ENABLED": str(os.getenv("ENABLE_WEBHOOK", "0")),
    }
    return safe


# --- Telegram helpers ---------------------------------------------------------
@app.get("/telegram/ping")
def telegram_ping() -> Dict[str, Any]:
    return {"ok": True}

@app.get("/telegram/webhook/info")
def telegram_webhook_info() -> Dict[str, Any]:
    cfg = Settings.build()
    ok, info = get_webhook_info(cfg.BOT_TOKEN)
    return {"ok": ok, "result": info}

@app.post("/telegram/webhook/set")
def telegram_webhook_set() -> Dict[str, Any]:
    cfg = Settings.build()
    public_url = cfg.PUBLIC_URL or os.getenv("PUBLIC_URL")
    if not public_url:
        return {"ok": False, "error": "PUBLIC_URL is not set"}
    wh_url = public_url.rstrip("/") + "/telegram"
    ok, resp = set_webhook(
        bot_token=cfg.BOT_TOKEN,
        webhook_url=wh_url,
        secret_token=cfg.TELEGRAM_SECRET_TOKEN or "",
        drop_pending=True,
    )
    return {"ok": ok, "result": resp, "url": wh_url}

@app.post("/telegram/webhook/delete")
def telegram_webhook_delete() -> Dict[str, Any]:
    cfg = Settings.build()
    ok, resp = delete_webhook(cfg.BOT_TOKEN, drop_pending=True)
    return {"ok": ok, "result": resp}


# --- Telegram webhook endpoint ------------------------------------------------
@app.post("/telegram")
async def telegram_webhook(request: Request) -> Response:
    cfg = Settings.build()

    # 1) Ğ¿Ñ€Ğ¾Ğ²ĞµÑ€ĞºĞ° ÑĞµĞºÑ€ĞµÑ‚Ğ°, ĞµÑĞ»Ğ¸ Ğ½Ğ°ÑÑ‚Ñ€Ğ¾ĞµĞ½
    if cfg.TELEGRAM_SECRET_TOKEN:
        if not validate_secret_header(
            request.headers, cfg.TELEGRAM_SECRET_TOKEN
        ):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"ok": False, "error": "bad secret"},
            )

    # 2) Ñ‡Ğ¸Ñ‚Ğ°ĞµĞ¼ Ğ°Ğ¿Ğ´ĞµĞ¹Ñ‚
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"ok": False, "error": "bad json"},
        )

    # 3) Ğ¾Ñ‚Ğ´Ğ°Ñ‘Ğ¼ Ğ² Ğ¾Ğ±Ñ€Ğ°Ğ±Ğ¾Ñ‚Ñ‡Ğ¸Ğº (ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼ Ğ¸ sync, Ğ¸ async)
    try:
        await dispatch_update(payload)
    except Exception:
        logger.exception("process_update failed")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"ok": False},  # Ğ²Ğ°Ğ¶Ğ½Ğ¾: Telegram Ğ¾Ğ¶Ğ¸Ğ´Ğ°ĞµÑ‚ 200, Ñ‡Ñ‚Ğ¾Ğ±Ñ‹ Ğ½Ğµ Ñ€ĞµÑ‚Ñ€Ğ°Ğ¸Ñ‚ÑŒ Ğ±ĞµÑĞºĞ¾Ğ½ĞµÑ‡Ğ½Ğ¾
        )

    return JSONResponse({"ok": True})



