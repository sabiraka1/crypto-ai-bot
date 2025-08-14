# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

import time
import requests
from fastapi import FastAPI, Request, Response, Header
from fastapi.responses import JSONResponse, PlainTextResponse

try:
    import ccxt
except Exception:
    ccxt = None

# Telegram bot helpers from our package
from crypto_ai_bot.telegram.bot import process_update, send_telegram_message
# Trading bot
from crypto_ai_bot.trading.bot import get_bot, Settings

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))

app = FastAPI(title="crypto-ai-bot", version=os.getenv("APP_VERSION", "1.0.0"))
_app_started_ts = time.time()

# ------------- Exchange adapter (ccxt) -------------
class ExchangeAdapter:
    def __init__(self):
        key = os.getenv("GATE_API_KEY") or os.getenv("API_KEY")
        secret = os.getenv("GATE_API_SECRET") or os.getenv("API_SECRET")
        self._ex = None
        if ccxt:
            self._ex = ccxt.gateio({
                "apiKey": key,
                "secret": secret,
                "enableRateLimit": True,
                "timeout": 20000,
                "options": {"defaultType": "spot"}
            })

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 200):
        if not self._ex: raise RuntimeError("ccxt not available")
        return self._ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def fetch_ticker(self, symbol: str):
        if not self._ex: return {}
        return self._ex.fetch_ticker(symbol)

    def create_order(self, symbol: str, type_: str, side: str, amount: float, params: Optional[Dict[str, Any]] = None):
        if not self._ex: raise RuntimeError("ccxt not available")
        params = params or {}
        if "text" not in params:
            import uuid
            params["text"] = f"bot-{uuid.uuid4().hex[:12]}"
        return self._ex.create_order(symbol, type_, side, amount, None, params)

# ------------- Startup: start trading loop + auto setWebhook -------------
_bot_started = False
_exchange: Optional[ExchangeAdapter] = None

def _telegram_api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"

def _try_get_webhook_info(token: str) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(_telegram_api(token, "getWebhookInfo"), timeout=10)
        if r.ok:
            return r.json()
    except Exception as e:
        logger.warning(f"getWebhookInfo failed: {e}")
    return None

def _ensure_webhook() -> None:
    enable = int(os.getenv("ENABLE_WEBHOOK", "0")) == 1
    token = os.getenv("BOT_TOKEN")
    public_url = os.getenv("PUBLIC_URL")
    secret_token = os.getenv("TELEGRAM_SECRET_TOKEN")
    if not enable:
        logger.info("ENABLE_WEBHOOK=0 → skipping auto setWebhook")
        return
    if not token or not public_url:
        logger.warning("Auto webhook skipped: BOT_TOKEN or PUBLIC_URL missing")
        return
    target_url = public_url.rstrip("/") + "/telegram/webhook"

    info = _try_get_webhook_info(token)
    current_url = None
    if info and info.get("ok"):
        result = info.get("result") or {}
        current_url = result.get("url") or ""
        has_custom_cert = result.get("has_custom_certificate")
        last_error = result.get("last_error_message")
        logger.info(f"getWebhookInfo: url={current_url!r}, has_cert={has_custom_cert}, last_error={last_error!r}")
    else:
        logger.info("getWebhookInfo: no data or not ok")

    if current_url != target_url:
        logger.info(f"setWebhook → {target_url}")
        payload = {"url": target_url}
        if secret_token:
            payload["secret_token"] = secret_token
        try:
            r = requests.post(_telegram_api(token, "setWebhook"), data=payload, timeout=10)
            ok = r.json().get("ok", False) if r.headers.get("Content-Type","").startswith("application/json") else r.ok
            logger.info(f"setWebhook result: {r.status_code} ok={ok} body={r.text[:200]}")
        except Exception as e:
            logger.warning(f"setWebhook failed: {e}")
    else:
        logger.info("Webhook already set to target URL; no changes")

@app.on_event("startup")
def startup_event():
    global _bot_started, _exchange
    # Trading loop start
    if not _exchange:
        _exchange = ExchangeAdapter()
    if not _bot_started and int(os.getenv("ENABLE_TRADING", "1")) == 1:
        bot = get_bot(exchange=_exchange, notifier=send_telegram_message, settings=Settings.build())
        bot.start()
        _bot_started = True
        logger.info("Trading bot started")
    else:
        logger.info("Trading bot NOT started (already started or disabled)")

    # Telegram auto webhook
    _ensure_webhook()

@app.on_event("shutdown")
def shutdown_event():
    logger.info("Shutting down app...")

# ------------- Routes -------------
@app.get("/health")
def health():
    return {"ok": True, "version": app.version, "web_concurrency": os.getenv("WEB_CONCURRENCY", "1")}

@app.get("/alive")
def alive():
    return {"alive": True}

@app.get("/metrics")
def metrics():
    ver = app.version
    uptime = time.time() - _app_started_ts
    body = []
    body.append('# HELP app_info Static app info')
    body.append('# TYPE app_info gauge')
    body.append(f'app_info{{version="{ver}"}} 1')
    body.append('# HELP app_uptime_seconds Uptime in seconds')
    body.append('# TYPE app_uptime_seconds counter')
    body.append(f'app_uptime_seconds {int(uptime)}')
    return PlainTextResponse("\n".join(body), media_type="text/plain; version=0.0.4; charset=utf-8")

@app.get("/telegram/ping")
def telegram_ping():
    send_telegram_message("🔔 server ping")
    return {"ok": True}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: Optional[str] = Header(default=None)):
    # Validate secret token if provided
    expected = os.getenv("TELEGRAM_SECRET_TOKEN")
    if expected:
        if not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token != expected:
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    logger.info(f"[WEBHOOK] keys={list(payload.keys())}, chat_id={(payload.get('message') or {}).get('chat',{}).get('id')}")
    await process_update(payload)
    return JSONResponse({"ok": True})
