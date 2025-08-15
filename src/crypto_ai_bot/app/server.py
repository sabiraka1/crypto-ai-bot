# -*- coding: utf-8 -*-
"""
FastAPI app entry with:
- webhook setup/validation
- /metrics, /config
- Telegram webhook handler -> telegram.bot.process_update
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.bot import get_bot

try:
    from crypto_ai_bot.telegram.bot import process_update
except Exception:  # pragma: no cover
    async def process_update(payload: Dict[str, Any]) -> None:
        pass

app = FastAPI(title="crypto-ai-bot")
_t0 = time.time()
_settings = Settings.build()

# optional exchange (do not fail if absent)
try:
    from crypto_ai_bot.trading.exchange_client import ExchangeClient  # type: ignore
    _exchange = ExchangeClient(_settings)  # type: ignore
except Exception:  # pragma: no cover
    _exchange = None

# simple notifier via Telegram sendMessage (optional)
async def send_telegram_message(text: str) -> None:
    token = _settings.BOT_TOKEN
    chat_id = _settings.CHAT_ID or (_settings.ADMIN_CHAT_IDS.split(",")[0] if _settings.ADMIN_CHAT_IDS else "")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text})

@app.on_event("startup")
def on_startup() -> None:
    # init bot singleton
    get_bot(exchange=_exchange, notifier=send_telegram_message, settings=_settings)
    # webhook auto-setup (optional)
    try:
        if int(os.getenv("ENABLE_WEBHOOK", "1")):
            public = os.getenv("PUBLIC_URL", "").rstrip("/")
            if public:
                url = f"{public}/telegram/webhook"
                token = _settings.BOT_TOKEN
                secret = _settings.TELEGRAM_SECRET_TOKEN
                payload = {"url": url, "secret_token": secret} if secret else {"url": url}
                httpx.post(f"https://api.telegram.org/bot{token}/setWebhook", json=payload, timeout=10)
                # check
                info = httpx.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10).json()
                logging.getLogger(__name__).info("Webhook info: %s", info)
    except Exception as e:  # pragma: no cover
        logging.getLogger(__name__).warning("webhook setup failed: %s", e)

# --- health/metrics ---
@app.get("/metrics")
async def metrics():
    return JSONResponse(
        {
            "app_info": {"version": "1.0.0"},
            "app_uptime_seconds": int(time.time() - _t0),
        }
    )

@app.get("/config")
async def config():
    cfg = _settings
    return {
        "SYMBOL": cfg.SYMBOL,
        "TIMEFRAME": cfg.TIMEFRAME,
        "ENABLE_TRADING": cfg.ENABLE_TRADING,
        "SAFE_MODE": cfg.SAFE_MODE,
        "PAPER_MODE": cfg.PAPER_MODE,
        "TRADE_AMOUNT": cfg.TRADE_AMOUNT,
        "AI_ENABLE": getattr(cfg, "AI_ENABLE", 0),
        "MIN_SCORE_TO_BUY": getattr(cfg, "MIN_SCORE_TO_BUY", 0.0),
    }

@app.get("/telegram/ping")
async def tg_ping():
    return {"ok": True}

# --- webhook ---
@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
):
    # validate secret if configured
    secret = _settings.TELEGRAM_SECRET_TOKEN
    if secret and x_telegram_bot_api_secret_token != secret:
        raise HTTPException(status_code=401, detail="unauthorized")

    payload = await request.json()
    try:
        await process_update(payload)  # expects async callable
    except TypeError:
        # in case process_update is sync
        process_update(payload)  # type: ignore
    except Exception as e:
        logging.getLogger(__name__).exception("process_update error: %s", e)
        return {"ok": False}
    return {"ok": True}
