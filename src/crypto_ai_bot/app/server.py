
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

# --- Project imports (core settings & bot factory) ---
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.trading.bot import get_bot

# Telegram adapter (expected to define: process_update(payload), send_telegram_message(...))
from crypto_ai_bot.telegram.bot import process_update, send_telegram_message

logger = logging.getLogger("server")
logging.basicConfig(level=getattr(logging, Settings.build().LOG_LEVEL.upper(), logging.INFO))

app = FastAPI(title="crypto-ai-bot")

# Prometheus metrics (minimal set)
STARTED = Gauge("app_started", "Application startup complete flag")
TG_UPDATES = Counter("tg_updates_total", "Total Telegram updates received")
TG_ERRORS = Counter("tg_update_errors_total", "Total errors processing Telegram updates")
WEBHOOK_SET = Gauge("telegram_webhook_set", "Telegram webhook set (1) or not (0)")

# Bot singleton holder
_bot_ready = False

async def _set_telegram_webhook(cfg: Settings) -> None:
    """Ensure Telegram webhook is set to PUBLIC_URL/telegram/webhook."""
    if not cfg.ENABLE_WEBHOOK:
        logger.info("ENABLE_WEBHOOK=0 → skip setWebhook")
        WEBHOOK_SET.set(0)
        return

    if not cfg.PUBLIC_URL:
        logger.warning("PUBLIC_URL is empty → skip setWebhook")
        WEBHOOK_SET.set(0)
        return

    url = cfg.PUBLIC_URL.rstrip('/') + "/telegram/webhook"
    api = f"https://api.telegram.org/bot{cfg.BOT_TOKEN}/setWebhook"
    payload = {
        "url": url,
        # secret_token validates X-Telegram-Bot-Api-Secret-Token header
        "secret_token": cfg.TELEGRAM_SECRET_TOKEN or cfg.WEBHOOK_SECRET or "telegram-secret",
        # drop_pending_updates could be false to keep backlog; set true if desired
        "drop_pending_updates": False,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(api, json=payload)
            ok = False
            if resp.status_code == 200:
                data = resp.json()
                ok = bool(data.get("ok"))
                if not ok:
                    logger.error("setWebhook failed: %s", data)
            else:
                logger.error("setWebhook HTTP %s: %s", resp.status_code, resp.text)
            WEBHOOK_SET.set(1 if ok else 0)
            if ok:
                logger.info("Webhook set to %s", url)
        except Exception as e:
            logger.exception("setWebhook error: %s", e)
            WEBHOOK_SET.set(0)

async def _check_webhook_info(cfg: Settings) -> Dict[str, Any]:
    api = f"https://api.telegram.org/bot{cfg.BOT_TOKEN}/getWebhookInfo"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(api)
        try:
            return resp.json()
        except Exception:
            return {"ok": False, "error": f"HTTP {resp.status_code}", "text": resp.text}

@app.on_event("startup")
async def on_startup() -> None:
    global _bot_ready
    cfg = Settings.build()

    # Try to build exchange (optional, depending on your factory signature)
    exchange = None
    try:
        from crypto_ai_bot.trading.exchange_client import ExchangeClient  # optional
        exchange = ExchangeClient(name=cfg.EXCHANGE_NAME, api_key=cfg.API_KEY, api_secret=cfg.API_SECRET)
    except Exception:
        # Fallback: let get_bot create/resolve exchange internally
        exchange = None

    # Build trading bot singleton
    try:
        get_bot(exchange=exchange, notifier=send_telegram_message, settings=cfg)
        _bot_ready = True
        logger.info("Trading bot initialized")
    except Exception as e:
        _bot_ready = False
        logger.exception("Bot init failed: %s", e)

    # Telegram webhook
    try:
        await _set_telegram_webhook(cfg)
        info = await _check_webhook_info(cfg)
        logger.info("WebhookInfo: %s", info)
    except Exception as e:
        logger.exception("Webhook setup/check failed: %s", e)

    STARTED.set(1)

@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "bot_ready": _bot_ready}

@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

def _redact_cfg(cfg: Settings) -> Dict[str, Any]:
    # Serialize non-sensitive snapshot
    # Adjust fields according to your Settings
    public = {
        k: getattr(cfg, k)
        for k in [
            "EXCHANGE_NAME", "SYMBOL", "TIMEFRAME",
            "ENABLE_TRADING", "SAFE_MODE", "PAPER_MODE",
            "TRADE_AMOUNT", "MAX_CONCURRENT_POS",
            "ATR_PERIOD", "TAKE_PROFIT_PCT", "STOP_LOSS_PCT",
            "TRAILING_STOP_ENABLE", "TRAILING_STOP_PCT",
            "DATA_DIR", "LOGS_DIR",
            "OHLCV_LIMIT", "AGGREGATOR_LIMIT",
            "ANALYSIS_INTERVAL", "LOG_LEVEL",
            "ENABLE_WEBHOOK", "PUBLIC_URL",
        ]
        if hasattr(cfg, k)
    }
    public["BOT_TOKEN"] = "****"  # never expose
    return public

@app.get("/config")
def config_view():
    cfg = Settings.build()
    return JSONResponse(_redact_cfg(cfg))

@app.get("/telegram/ping")
def telegram_ping():
    return {"ok": True}

@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None, convert_underscores=False),
):
    cfg = Settings.build()

    # Secret token validation (optional but recommended)
    expected = cfg.TELEGRAM_SECRET_TOKEN or cfg.WEBHOOK_SECRET
    if expected:
        if x_telegram_bot_api_secret_token != expected:
            TG_ERRORS.inc()
            raise HTTPException(status_code=401, detail="Invalid telegram secret token")

    # Parse incoming update
    try:
        payload = await request.json()
    except Exception:
        TG_ERRORS.inc()
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Dispatch to bot's update processor (supports sync/async)
    try:
        res = process_update(payload)
        if inspect.iscoroutine(res):
            await res
        TG_UPDATES.inc()
        return {"ok": True}
    except Exception as e:
        TG_ERRORS.inc()
        logger.exception("process_update error: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

# Manual webhook controls (optional)
@app.post("/telegram/setwebhook")
async def set_webhook_manual():
    cfg = Settings.build()
    await _set_telegram_webhook(cfg)
    info = await _check_webhook_info(cfg)
    return info

@app.get("/telegram/getwebhook")
async def get_webhook_manual():
    cfg = Settings.build()
    return await _check_webhook_info(cfg)

@app.post("/telegram/delwebhook")
async def delete_webhook_manual():
    cfg = Settings.build()
    api = f"https://api.telegram.org/bot{cfg.BOT_TOKEN}/deleteWebhook"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(api)
        return r.json()
