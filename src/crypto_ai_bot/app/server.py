
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

try:
    import ccxt
except Exception:
    ccxt = None

from crypto_ai_bot.trading.bot import get_bot, Settings
from crypto_ai_bot.telegram.bot import process_update, send_telegram_message

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))

app = FastAPI(title="crypto-ai-bot", version=os.getenv("APP_VERSION", "1.0.0"))
_start_time = time.time()
_bot_started = False

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

_exchange: Optional[ExchangeAdapter] = None

@app.on_event("startup")
def startup_event():
    global _bot_started, _exchange
    if not _exchange:
        _exchange = ExchangeAdapter()
    if not _bot_started and int(os.getenv("ENABLE_TRADING", "1")) == 1:
        bot = get_bot(exchange=_exchange, notifier=send_telegram_message, settings=Settings.build())
        bot.start()
        _bot_started = True
        logger.info("Trading bot started")
    else:
        logger.info("Trading bot NOT started (already started or disabled)")

@app.get("/health")
def health():
    return {"ok": True, "version": app.version, "web_concurrency": os.getenv("WEB_CONCURRENCY", "1")}

@app.get("/alive")
def alive():
    return {"alive": True}

@app.get("/metrics")
def metrics():
    uptime = time.time() - _start_time
    version = app.version
    payload = (
        f'app_info{{version="{version}"}} 1\n'
        f"app_uptime_seconds {uptime:.0f}\n"
    )
    return PlainTextResponse(payload, media_type="text/plain; version=0.0.4; charset=utf-8")

@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    try:
        payload = await req.json()
    except Exception:
        payload = {}
    await process_update(payload)
    return JSONResponse({"ok": True})
