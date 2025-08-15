# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

# Единый конфиг
from crypto_ai_bot.core.settings import Settings

# Биржевой клиент и единая точка входа для бота
from crypto_ai_bot.trading.exchange_client import ExchangeClient
from crypto_ai_bot.trading.bot import get_bot

# Телеграм-логика (через модуль бота); используем если доступна
try:
    from crypto_ai_bot.telegram import bot as tgbot  # ожидаем tg_send_message, process_update
except Exception:  # модуль может отсутствовать при некоторых сборках
    tgbot = None  # type: ignore

logger = logging.getLogger("crypto_ai_bot.app.server")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())


app = FastAPI(title="crypto-ai-bot", version="1.0.0")

# Глобальные singletons
_settings: Optional[Settings] = None
_exchange: Optional[ExchangeClient] = None


def _set_webhook_if_possible(cfg: Settings) -> tuple[bool, Any]:
    """
    Ставит Telegram webhook, если есть токен и PUBLIC_URL.
    Возвращает (ok, resp_or_error).
    """
    token = cfg.TELEGRAM_BOT_TOKEN
    public_url = cfg.PUBLIC_URL
    if not token or not public_url:
        return False, "skip (no token or PUBLIC_URL)"

    api_url = f"https://api.telegram.org/bot{token}/setWebhook"
    payload = {
        "url": f"{public_url}/telegram",
        "secret_token": cfg.TELEGRAM_SECRET_TOKEN or "",
        "drop_pending_updates": True,
    }
    try:
        import requests  # используем, если есть в окружении
        r = requests.post(api_url, json=payload, timeout=10)
        ok = r.ok
        try:
            data = r.json()
        except Exception:
            data = {"text": r.text}
        return ok, data
    except Exception as e:
        logger.warning("setWebhook request failed: %s", e)
        return False, str(e)


def _get_webhook_info(cfg: Settings) -> tuple[bool, Any]:
    token = cfg.TELEGRAM_BOT_TOKEN
    if not token:
        return False, "skip (no token)"
    url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    try:
        import requests
        r = requests.get(url, timeout=10)
        ok = r.ok
        try:
            data = r.json()
        except Exception:
            data = {"text": r.text}
        return ok, data
    except Exception as e:
        logger.warning("getWebhookInfo failed: %s", e)
        return False, str(e)


def send_telegram_message(text: str) -> None:
    """
    Унифицированный notifier для торгового бота.
    Использует tg_send_message(chat_id, text), если модуль доступен.
    """
    try:
        if tgbot is None:
            return
        if _settings and getattr(_settings, "TELEGRAM_CHAT_ID", None):
            tgbot.tg_send_message(_settings.TELEGRAM_CHAT_ID, text)  # type: ignore[attr-defined]
    except Exception as e:
        logger.warning("tg notify failed: %s", e)


@app.on_event("startup")
def on_startup() -> None:
    global _settings, _exchange
    # Единый конфиг
    _settings = Settings.build()
    logger.info("Startup with SYMBOL=%s TIMEFRAME=%s", _settings.SYMBOL, _settings.TIMEFRAME)

    # Создаём клиент биржи один раз
    if _exchange is None:
        _exchange = ExchangeClient(_settings)

    # Инициализируем торговый бот
    try:
        get_bot(exchange=_exchange, notifier=send_telegram_message, settings=_settings)  # type: ignore[arg-type]
    except Exception as e:
        logger.error("Trading bot init failed — %s", e)

    # Ставим webhook (best-effort)
    try:
        ok, resp = _set_webhook_if_possible(_settings)
        logger.info("setWebhook(%s/telegram) → ok=%s resp=%s", _settings.PUBLIC_URL, ok, resp)
        ok2, info = _get_webhook_info(_settings)
        logger.info("getWebhookInfo → ok=%s info=%s", ok2, info)
    except Exception as e:
        logger.warning("Webhook check failed: %s", e)


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "name": "crypto-ai-bot",
        "version": app.version,
        "symbol": Settings.SYMBOL,
        "timeframe": Settings.TIMEFRAME,
        "public_url": os.getenv("PUBLIC_URL", ""),
        "ok": True,
    }


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    # Минимальная проверка «живости»: конфиг загрузился
    return {"ok": True, "cfg_loaded": _settings is not None}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    # Простейшие метрики (без зависимостей от prometheus_client)
    lines = [
        "# HELP app_up 1 if app is up",
        "# TYPE app_up gauge",
        "app_up 1",
    ]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.get("/config")
def config_endpoint() -> JSONResponse:
    cfg = _settings or Settings.build()
    hidden = {"TELEGRAM_BOT_TOKEN"}  # токен не светим
    data = {k: (None if k in hidden else getattr(cfg, k)) for k in cfg.__annotations__.keys()}  # type: ignore
    return JSONResponse(data)


@app.post("/telegram")
async def telegram_webhook(request: Request) -> JSONResponse:
    """
    Вебхук для Telegram:
    - проверяем секрет из заголовка X-Telegram-Bot-Api-Secret-Token;
    - пробрасываем апдейт в telegram.bot.process_update(payload).
    """
    cfg = _settings or Settings.build()
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if cfg.TELEGRAM_SECRET_TOKEN and secret != cfg.TELEGRAM_SECRET_TOKEN:
        return JSONResponse({"ok": False, "description": "bad secret"}, status_code=403)

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    try:
        if tgbot and hasattr(tgbot, "process_update"):
            # Совместимость: process_update может быть sync/async
            res = tgbot.process_update(payload)  # type: ignore[attr-defined]
            if hasattr(res, "__await__"):
                await res  # если корутина
        else:
            logger.debug("tgbot.process_update is not available — skip")
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.exception("process_update error")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
