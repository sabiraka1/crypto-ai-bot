# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse

# Ğ•Ğ´Ğ¸Ğ½Ñ‹Ğ¹ ĞºĞ¾Ğ½Ñ„Ğ¸Ğ³
from crypto_ai_bot.core.settings import Settings

# Ğ‘Ğ¸Ñ€Ğ¶ĞµĞ²Ğ¾Ğ¹ ĞºĞ»Ğ¸ĞµĞ½Ñ‚ Ğ¸ ĞµĞ´Ğ¸Ğ½Ğ°Ñ Ñ‚Ğ¾Ñ‡ĞºĞ° Ğ²Ñ…Ğ¾Ğ´Ğ° Ğ´Ğ»Ñ Ğ±Ğ¾Ñ‚Ğ°
from crypto_ai_bot.trading.exchange_client import ExchangeClient
from crypto_ai_bot.trading.bot import get_bot, TradingBot

# Ğ¢ĞµĞ»ĞµĞ³Ñ€Ğ°Ğ¼ Ñ‡ĞµÑ€ĞµĞ· Ğ°Ğ´Ğ°Ğ¿Ñ‚ĞµÑ€ (ĞµÑĞ»Ğ¸ ĞµÑÑ‚ÑŒ)
try:
    from crypto_ai_bot.telegram import bot as tgbot  # tg_send_message, process_update
except Exception:
    tgbot = None  # ĞŸĞ¾Ğ·Ğ²Ğ¾Ğ»ÑĞµÑ‚ Ğ·Ğ°Ğ¿ÑƒÑĞºĞ°Ñ‚ÑŒÑÑ Ğ´Ğ°Ğ¶Ğµ Ğ±ĞµĞ· telegram-Ğ¼Ğ¾Ğ´ÑƒĞ»Ñ

# Ğ£Ğ½Ğ¸Ñ„Ğ¸Ñ†Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğ¹ HTTP-ĞºĞ»Ğ¸ĞµĞ½Ñ‚ Ğ´Ğ»Ñ Telegram webhook mgmt
from crypto_ai_bot.utils.http_client import http_get, http_post

logger = logging.getLogger("crypto_ai_bot.app.server")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="crypto-ai-bot")

# Ğ“Ğ»Ğ¾Ğ±Ğ°Ğ»ÑŒĞ½Ñ‹Ğµ singletons
_settings: Optional[Settings] = None
_exchange: Optional[ExchangeClient] = None
_bot: Optional[TradingBot] = None


def _set_webhook_if_possible(cfg: Settings) -> tuple[bool, Dict[str, Any]]:
    """
    Ğ¡Ñ‚Ğ°Ğ²Ğ¸Ñ‚ Telegram webhook, ĞµÑĞ»Ğ¸ ĞµÑÑ‚ÑŒ Ñ‚Ğ¾ĞºĞµĞ½ Ğ¸ PUBLIC_URL. Ğ’Ğ¾Ğ·Ğ²Ñ€Ğ°Ñ‰Ğ°ĞµÑ‚ (ok, resp).
    """
    if not (cfg.BOT_TOKEN and cfg.PUBLIC_URL):
        return False, {"reason": "no BOT_TOKEN or PUBLIC_URL"}
    url = f"https://api.telegram.org/bot{cfg.BOT_TOKEN}/setWebhook"
    payload = {
        "url": f"{cfg.PUBLIC_URL.rstrip('/')}/telegram",
        "secret_token": cfg.TELEGRAM_SECRET_TOKEN or "",
    }
    try:
        r = http_post(url, json=payload, timeout=10)
        j = r.json()
        return bool(j.get("ok", False)), j
    except Exception as e:
        return False, {"error": str(e)}


def _get_webhook_info(cfg: Settings) -> tuple[bool, Dict[str, Any]]:
    if not cfg.BOT_TOKEN:
        return False, {"reason": "no BOT_TOKEN"}
    url = f"https://api.telegram.org/bot{cfg.BOT_TOKEN}/getWebhookInfo"
    try:
        r = http_get(url, timeout=10)
        j = r.json()
        return bool(j.get("ok", False)), j
    except Exception as e:
        return False, {"error": str(e)}


def _notifier_text(text: str) -> None:
    """
    Ğ£Ğ½Ğ¸Ñ„Ğ¸Ñ†Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğ¹ notifier Ğ´Ğ»Ñ Ñ‚Ğ¾Ñ€Ğ³Ğ¾Ğ²Ğ¾Ğ³Ğ¾ Ğ±Ğ¾Ñ‚Ğ°.
    """
    cfg = _settings or Settings.build()
    if tgbot and cfg.CHAT_ID:
        try:
            tgbot.tg_send_message(int(cfg.CHAT_ID), text, cfg=cfg)
        except Exception as e:
            logger.warning("Notifier send failed: %s", e)
    else:
        logger.info("NOTIFY: %s", text)


@app.on_event("startup")
def on_startup() -> None:
    global _settings, _exchange, _bot
    cfg = Settings.build()
    _settings = cfg

    logger.info("Startup with SYMBOL=%s TIMEFRAME=%s", cfg.SYMBOL, cfg.TIMEFRAME)

    # Ğ¡Ğ¾Ğ·Ğ´Ğ°Ñ‘Ğ¼ ĞºĞ»Ğ¸ĞµĞ½Ñ‚ Ğ±Ğ¸Ñ€Ğ¶Ğ¸ Ğ¾Ğ´Ğ¸Ğ½ Ñ€Ğ°Ğ·
    _exchange = ExchangeClient(cfg)

    # Ğ˜Ğ½Ğ¸Ñ†Ğ¸Ğ°Ğ»Ğ¸Ğ·Ğ¸Ñ€ÑƒĞµĞ¼ Ñ‚Ğ¾Ñ€Ğ³Ğ¾Ğ²Ñ‹Ğ¹ Ğ±Ğ¾Ñ‚ (singleton)
    try:
        _bot = get_bot(exchange=_exchange, notifier=_notifier_text, settings=cfg)
        # Ğ•ÑĞ»Ğ¸ Ñƒ Ğ±Ğ¾Ñ‚Ğ° ĞµÑÑ‚ÑŒ Ñ„Ğ¾Ğ½Ğ¾Ğ²Ğ°Ñ Ğ¿ĞµÑ‚Ğ»Ñ â€” ÑÑ‚Ğ°Ñ€Ñ‚ÑƒĞµĞ¼ ĞµÑ‘
        if hasattr(_bot, "start"):
            _bot.start()  # ĞµÑĞ»Ğ¸ Ñ€ĞµĞ°Ğ»Ğ¸Ğ·Ğ¾Ğ²Ğ°Ğ½Ğ¾
        elif hasattr(_bot, "ensure_loop_thread"):
            _bot.ensure_loop_thread()  # Ğ°Ğ»ÑŒÑ‚ĞµÑ€Ğ½Ğ°Ñ‚Ğ¸Ğ²Ğ½Ğ¾Ğµ Ğ¸Ğ¼Ñ
    except Exception as e:
        logger.error("Trading bot init failed â€” %s", e)

    # Ğ¡Ñ‚Ğ°Ğ²Ğ¸Ğ¼ webhook (best-effort)
    try:
        ok, resp = _set_webhook_if_possible(cfg)
        logger.info("setWebhook(%s/telegram) â†’ ok=%s resp=%s",
                    cfg.PUBLIC_URL, ok, resp)
        ok2, info = _get_webhook_info(cfg)
        logger.info("getWebhookInfo â†’ ok=%s info=%s", ok2, info)
    except Exception as e:
        logger.warning("Webhook setup skipped: %s", e)


@app.get("/health")
def health() -> JSONResponse:
    cfg = _settings or Settings.build()
    data = {
        "ok": True,
        "symbol": cfg.SYMBOL,
        "timeframe": cfg.TIMEFRAME,
        "webhook": bool(cfg.BOT_TOKEN and cfg.PUBLIC_URL),
        "bot_initialized": bool(_bot is not None),
    }
    return JSONResponse(data)


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    # ĞŸÑ€Ğ¾ÑÑ‚ĞµĞ¹ÑˆĞ¸Ğµ Ğ¼ĞµÑ‚Ñ€Ğ¸ĞºĞ¸ Ğ±ĞµĞ· prometheus_client
    lines = []
    lines.append('app_up 1')
    return PlainTextResponse("\n".join(lines))


@app.get("/config")
def config() -> JSONResponse:
    cfg = _settings or Settings.build()
    hidden = {"BOT_TOKEN", "TELEGRAM_SECRET_TOKEN", "GATE_API_SECRET", "API_SECRET"}
    data = {k: (v if k not in hidden else "***") for k, v in cfg.__dict__.items()}
    return JSONResponse(data)


@app.post("/telegram")
async def telegram_webhook(request: Request) -> Response:
    cfg = _settings or Settings.build()

    # Ğ’Ğ°Ğ»Ğ¸Ğ´Ğ°Ñ†Ğ¸Ñ ÑĞµĞºÑ€ĞµÑ‚Ğ°
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
    if (cfg.TELEGRAM_SECRET_TOKEN or "") != secret:
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    if tgbot and hasattr(tgbot, "process_update"):
        try:
            res = tgbot.process_update(payload, cfg=cfg)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            logger.exception("process_update error: %s", e)
            return Response(status_code=status.HTTP_200_OK)
    else:
        logger.debug("tgbot.process_update unavailable â€” skip")

    return Response(status_code=status.HTTP_200_OK)

