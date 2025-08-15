# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import logging
import time
from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse, PlainTextResponse

try:
    import ccxt
except Exception:  # pragma: no cover
    ccxt = None

# Import Telegram update dispatcher from our bot module
try:
    from crypto_ai_bot.telegram.bot import process_update
except Exception:
    process_update = None  # graceful if telegram module missing

# Import Trading bot
from crypto_ai_bot.trading.bot import get_bot, Settings

# ------------ logging ------------
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))

app = FastAPI(title="crypto-ai-bot", version=os.getenv("APP_VERSION", "1.0.0"))
_start_ts = time.time()


# ------------ helpers ------------
def send_telegram_message(text: str):
    token = os.getenv("BOT_TOKEN")
    chat_ids = os.getenv("ADMIN_CHAT_IDS") or ""
    if not token or not chat_ids:
        logger.info(f"[TELEGRAM DISABLED] {text}")
        return
    for chat in chat_ids.split(","):
        chat = chat.strip()
        if not chat:
            continue
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = {
                "chat_id": chat,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            logger.warning(f"telegram send failed: {e}")


class ExchangeAdapter:
    def __init__(self):
        key = os.getenv("GATE_API_KEY") or os.getenv("API_KEY")
        secret = os.getenv("GATE_API_SECRET") or os.getenv("API_SECRET")
        self._ex = None
        if ccxt:
            self._ex = ccxt.gateio(
                {
                    "apiKey": key,
                    "secret": secret,
                    "enableRateLimit": True,
                    "timeout": 20000,
                    "options": {"defaultType": "spot"},
                }
            )

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 200):
        if not self._ex:
            raise RuntimeError("ccxt not available")
        return self._ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def fetch_ticker(self, symbol: str):
        if not self._ex:
            return {}
        return self._ex.fetch_ticker(symbol)

    def create_order(self, symbol: str, type_: str, side: str, amount: float, params: Optional[Dict[str, Any]] = None):
        if not self._ex:
            raise RuntimeError("ccxt not available")
        params = params or {}
        if "text" not in params:
            import uuid

            params["text"] = f"bot-{uuid.uuid4().hex[:12]}"
        return self._ex.create_order(symbol, type_, side, amount, None, params)


# ------------ lifecycle ------------
_bot_started = False
_exchange: Optional[ExchangeAdapter] = None


def _webhook_target_url() -> Optional[str]:
    base = os.getenv("PUBLIC_URL", "").rstrip("/")
    if not base:
        return None
    return f"{base}/telegram/webhook"


def _get_webhook_info(token: str) -> Dict[str, Any]:
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10)
        return r.json()
    except Exception as e:
        logger.warning(f"getWebhookInfo failed: {e}")
        return {"ok": False, "error": str(e)}


def _set_webhook(token: str, url: str, secret: Optional[str]) -> Dict[str, Any]:
    try:
        data = {"url": url}
        if secret:
            data["secret_token"] = secret
        r = requests.post(f"https://api.telegram.org/bot{token}/setWebhook", data=data, timeout=10)
        return r.json()
    except Exception as e:
        logger.warning(f"setWebhook failed: {e}")
        return {"ok": False, "error": str(e)}


@app.on_event("startup")
def on_startup():
    global _bot_started, _exchange
    logger.info("Application startup...")

    # start trading bot (single instance)
    if not _exchange:
        _exchange = ExchangeAdapter()
    if not _bot_started and int(os.getenv("ENABLE_TRADING", "1")) == 1:
        bot = get_bot(exchange=_exchange, notifier=send_telegram_message, settings=Settings.build())
        bot.start()
        _bot_started = True
        logger.info("Trading bot started")
    else:
        logger.info("Trading bot NOT started (already started or disabled)")

    # auto webhook
    if int(os.getenv("ENABLE_WEBHOOK", "0")) == 1:
        token = os.getenv("BOT_TOKEN")
        secret = os.getenv("TELEGRAM_SECRET_TOKEN")
        target = _webhook_target_url()
        if token and target:
            info = _get_webhook_info(token)
            current_url = (info.get("result") or {}).get("url") if info.get("ok") else None
            logger.info(f"[webhook] getWebhookInfo ok={info.get('ok')} url={current_url}")
            if current_url != target:
                res = _set_webhook(token, target, secret)
                logger.info(f"[webhook] setWebhook result ok={res.get('ok')}")
        else:
            logger.info("[webhook] skipped (no BOT_TOKEN or PUBLIC_URL)")


# ------------ routes ------------
@app.get("/health")
def health():
    return {"ok": True, "version": app.version, "web_concurrency": os.getenv("WEB_CONCURRENCY", "1")}


@app.get("/alive")
def alive():
    return {"alive": True}


@app.get("/metrics")
def metrics():
    # minimal Prometheus metrics
    uptime = int(time.time() - _start_ts)
    lines = [
        f'app_info{{version="{app.version}"}} 1',
        f"app_uptime_seconds {uptime}",
    ]
    return PlainTextResponse("\n".join(lines), media_type="text/plain; version=0.0.4")


@app.get("/telegram/ping")
def telegram_ping():
    send_telegram_message("🔔 server ping")
    return {"ok": True}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: Optional[str] = Header(default=None)):
    # optional secret token enforcement
    expected = os.getenv("TELEGRAM_SECRET_TOKEN")
    if expected:
        if not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token != expected:
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    logger.info(f"[WEBHOOK] keys={list(payload.keys())}")
    if process_update is not None:
        try:
            await process_update(payload)
        except Exception as e:
            logger.exception(f"process_update error: {e}")
    return JSONResponse({"ok": True})
