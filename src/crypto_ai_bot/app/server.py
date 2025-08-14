# -*- coding: utf-8 -*-
from __future__ import annotations

"""
crypto_ai_bot/app/server.py
----------------------------
Объединённая версия server.corrected.py и server.py
- Полная интеграция с Telegram-ботом (process_update)
- Fallback-отправка сообщений при недоступном боте
- Сохраняет все эндпоинты и логику старта торгового бота
"""

import os
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

try:
    import ccxt
except Exception:
    ccxt = None

import requests

# Импортируем реальный Telegram-бот
try:
    from crypto_ai_bot.telegram.bot import process_update, send_telegram_message as bot_send_message
except ImportError:
    process_update = None
    bot_send_message = None

from crypto_ai_bot.trading.bot import get_bot, Settings

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))

app = FastAPI(title="crypto-ai-bot", version=os.getenv("APP_VERSION", "1.0.0"))

# ----------- Telegram notifier (с fallback) -----------

def send_telegram_message(text: str, image_path: Optional[str] = None):
    """Отправка через встроенный бот или напрямую через Telegram API"""
    if bot_send_message:
        try:
            bot_send_message(text)
            return
        except Exception as e:
            logger.warning(f"[TELEGRAM BOT ERROR] {e}, fallback to direct send")

    token = os.getenv("BOT_TOKEN")
    chat_ids = os.getenv("ADMIN_CHAT_IDS") or os.getenv("CHAT_ID")
    if not token or not chat_ids:
        logger.info(f"[TELEGRAM DISABLED] {text}")
        return

    for chat in str(chat_ids).split(","):
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = {
                "chat_id": chat.strip(),
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            logger.warning(f"[TELEGRAM FALLBACK ERROR] {e}")

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

# ----------- Lifecycle -----------

_bot_started = False
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

@app.on_event("shutdown")
def shutdown_event():
    logger.info("Shutting down app...")

# ----------- Routes -----------

@app.get("/health")
def health():
    return {
        "ok": True,
        "version": app.version,
        "web_concurrency": os.getenv("WEB_CONCURRENCY", "1")
    }

@app.get("/alive")
def alive():
    return {"alive": True}

@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    """Приём обновлений Telegram и передача в бот, с логированием"""
    try:
        payload = await req.json()
    except Exception:
        payload = {}

    logger.info(f"[WEBHOOK] update_id={payload.get('update_id')} keys={list(payload.keys())}")

    if process_update:
        try:
            await process_update(payload)
        except Exception as e:
            logger.error(f"Error in process_update: {e}")
    else:
        logger.warning("process_update not available, skipping bot handling")

    return JSONResponse({"ok": True})
