# -*- coding: utf-8 -*-
from __future__ import annotations

"""
crypto_ai_bot/app/server.py
----------------------------
FastAPI-приложение для Railway с безопасным стартом торгового цикла.
- Старт бота на событии startup (синглтон, не плодит циклы).
- /health, /alive — для проверок.
- /telegram/webhook — приём Telegram-обновлений (минимум логики, можно прокинуть в существующий telegram_bot).
- ExchangeAdapter — тонкая обёртка вокруг ccxt.gateio без новых файлов.
"""

import os
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

try:
    import ccxt
except Exception:  # pragma: no cover
    ccxt = None

import requests

from crypto_ai_bot.trading.bot import get_bot, Settings

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))

app = FastAPI(title="crypto-ai-bot", version=os.getenv("APP_VERSION", "1.0.0"))

# ----------- Telegram notifier -----------

def send_telegram_message(text: str, image_path: Optional[str] = None):
    token = os.getenv("BOT_TOKEN")
    chat_ids = os.getenv("ADMIN_CHAT_IDS") or os.getenv("CHAT_ID")
    if not token or not chat_ids:
        logger.info(f"[TELEGRAM DISABLED] {text}")
        return
    for chat in str(chat_ids).split(","):
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = {"chat_id": chat.strip(), "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            logger.warning(f"telegram send failed: {e}")


# ----------- ccxt exchange adapter -----------

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

    # TradingBot ожидает эти методы:
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
        # Gate.io клиентский тэг:
        if "text" not in params:
            import uuid
            params["text"] = f"bot-{uuid.uuid4().hex[:12]}"
        return self._ex.create_order(symbol, type_, side, amount, None, params)


# ----------- Lifecycle -----------

_bot_started = False
_exchange: Optional[ExchangeAdapter] = None

@app.on_event("startup")
def startup_event():
    global _bot_started, _exchange
    if not _exchange:
        _exchange = ExchangeAdapter()
    # единичный запуск бота
    if not _bot_started and int(os.getenv("ENABLE_TRADING", "1")) == 1:
        bot = get_bot(exchange=_exchange, notifier=send_telegram_message, settings=Settings.build())
        bot.start()
        _bot_started = True
        logger.info("Trading bot started in startup_event()")
    else:
        logger.info("Trading bot NOT started (already started or ENABLE_TRADING=0)")

@app.on_event("shutdown")
def shutdown_event():
    logger.info("Shutting down app...")


# ----------- Routes -----------

@app.get("/health")
def health():
    return {"ok": True, "version": app.version, "web_concurrency": os.getenv("WEB_CONCURRENCY", "1")}

@app.get("/alive")
def alive():
    return {"alive": True}

@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    """Приём обновлений Telegram. Если есть свой telegram_bot — можно прокинуть туда логику здесь."""
    try:
        payload = await req.json()
    except Exception:
        payload = {}
    # Минимальная обработка: просто логирование и ACK
    logger.info(f"[WEBHOOK] update_id={payload.get('update_id')} keys={list(payload.keys())}")
    return JSONResponse({"ok": True})

