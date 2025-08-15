# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse

# Единый конфиг
from crypto_ai_bot.core.settings import Settings

# Биржевой клиент и единая точка входа для бота
from crypto_ai_bot.trading.exchange_client import ExchangeClient
from crypto_ai_bot.trading.bot import get_bot, TradingBot

# Телеграм через адаптер (если есть)
try:
    from crypto_ai_bot.telegram import bot as tgbot  # tg_send_message, process_update
except Exception:
    tgbot = None  # Позволяет запускаться даже без telegram-модуля

# Унифицированный HTTP-клиент для Telegram webhook mgmt
from crypto_ai_bot.utils.http_client import http_get, http_post

logger = logging.getLogger("crypto_ai_bot.app.server")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="crypto-ai-bot")

# Глобальные singletons
_settings: Optional[Settings] = None
_exchange: Optional[ExchangeClient] = None
_bot: Optional[TradingBot] = None


def _set_webhook_if_possible(cfg: Settings) -> tuple[bool, Dict[str, Any]]:
    """
    Ставит Telegram webhook, если есть токен и PUBLIC_URL. Возвращает (ok, resp).
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
    Унифицированный notifier для торгового бота.
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

    # Создаём клиент биржи один раз
    _exchange = ExchangeClient(cfg)

    # Инициализируем торговый бот (singleton)
    try:
        _bot = get_bot(exchange=_exchange, notifier=_notifier_text, settings=cfg)
        # Если у бота есть фоновая петля — стартуем её
        if hasattr(_bot, "start"):
            _bot.start()  # если реализовано
        elif hasattr(_bot, "ensure_loop_thread"):
            _bot.ensure_loop_thread()  # альтернативное имя
    except Exception as e:
        logger.error("Trading bot init failed — %s", e)

    # Ставим webhook (best-effort)
    try:
        ok, resp = _set_webhook_if_possible(cfg)
        logger.info("setWebhook(%s/telegram) → ok=%s resp=%s",
                    cfg.PUBLIC_URL, ok, resp)
        ok2, info = _get_webhook_info(cfg)
        logger.info("getWebhookInfo → ok=%s info=%s", ok2, info)
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
    # Простейшие метрики без prometheus_client
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

    # Валидация секрета
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
        logger.debug("tgbot.process_update unavailable — skip")

    return Response(status_code=status.HTTP_200_OK)
