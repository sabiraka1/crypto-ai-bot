# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

# Единый конфиг
from crypto_ai_bot.core.settings import Settings

# Биржевой клиент и единая точка входа для бота (импорт с запасом)
try:
    from crypto_ai_bot.core.bot import get_bot  # type: ignore
except Exception:  # старые деревья
    from crypto_ai_bot.trading.bot import get_bot  # type: ignore

# Телеграм-утилиты (если модуль присутствует)
try:
    from crypto_ai_bot.telegram import bot as tgbot  # ожидаем tg_send_message, process_update, init
except Exception:
    tgbot = None  # type: ignore

# Единый HTTP-клиент (без прямых requests.*)
from crypto_ai_bot.utils.http_client import http_get, http_post  # -> (ok: bool, data|err)

logger = logging.getLogger("crypto_ai_bot.app.server")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

app = FastAPI(title="crypto-ai-bot")

# Глобальные singletons
_settings: Optional[Settings] = None
_bot = None
_exchange: Any = None


def _telegram_set_webhook(base_url: str, token: str, secret: Optional[str]):
    """
    Ставит Telegram webhook, если есть токен и PUBLIC_URL.
    Возвращает (ok, resp_or_error).
    """
    api = f"https://api.telegram.org/bot{token}/setWebhook"
    payload = {"url": f"{base_url.rstrip('/')}/telegram"}
    if secret:
        payload["secret_token"] = secret
    ok, data = http_post(api, json=payload, timeout=10)
    return ok, data


def _telegram_get_webhook_info(token: str):
    api = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    ok, data = http_get(api, timeout=10)
    return ok, data


def _safe_settings_dump(cfg: Settings) -> dict:
    d = json.loads(cfg.model_dump_json()) if hasattr(cfg, "model_dump_json") else dict(cfg.__dict__)
    # маскируем чувствительные поля
    for k in list(d.keys()):
        if "TOKEN" in k or "SECRET" in k or "KEY" in k:
            val = str(d.get(k, ""))
            if val:
                d[k] = val[:4] + "***"
    return d


def _notify(text: str) -> None:
    """Унифицированный notifier для торгового бота."""
    try:
        if tgbot and hasattr(tgbot, "tg_send_message"):
            # chat_id берётся внутри tgbot из Settings, если не передан
            tgbot.tg_send_message(text)  # type: ignore[attr-defined]
        else:
            logger.info("[Telegram muted] %s", text)
    except Exception as e:
        logger.warning("Notifier failed: %s", e)


@app.on_event("startup")
def on_startup():
    global _settings, _bot, _exchange

    # 1) Единый конфиг
    _settings = Settings.build()
    logger.info("Startup with SYMBOL=%s TIMEFRAME=%s", _settings.SYMBOL, _settings.TIMEFRAME)

    # 2) Инициализируем telegram-модуль (передаем Settings внутрь)
    try:
        if tgbot and hasattr(tgbot, "init"):
            tgbot.init(_settings)  # type: ignore[attr-defined]
    except Exception as e:
        logger.warning("telegram.init skipped: %s", e)

    # 3) Создаём клиент биржи (best-effort, без падений)
    try:
        # пробуем разные варианты из старых деревьев
        try:
            from crypto_ai_bot.trading.exchange_client import create_exchange_client  # type: ignore

            _exchange = create_exchange_client(_settings)  # type: ignore
        except Exception:
            try:
                from crypto_ai_bot.trading.exchange_client import ExchangeClient  # type: ignore

                # сигнатуры разные в ветках — пробуем без именованных аргументов
                _exchange = ExchangeClient(_settings)  # type: ignore
            except Exception:
                _exchange = None
    except Exception as e:
        logger.warning("Exchange init failed (non-fatal): %s", e)
        _exchange = None

    # 4) Инициализируем торговый бот (без bot.start(); петля — на совести самого бота)
    try:
        _bot = get_bot(exchange=_exchange, notifier=_notify, settings=_settings)  # type: ignore[call-arg]
    except TypeError:
        # старые сигнатуры
        try:
            _bot = get_bot(_exchange, _notify, _settings)  # type: ignore[misc]
        except Exception as e2:
            logger.error("Trading bot init failed — %s", e2)
            _bot = None
    except Exception as e:
        logger.error("Trading bot init failed — %s", e)
        _bot = None

    # 5) Ставим webhook (best-effort)
    try:
        if _settings.TELEGRAM_BOT_TOKEN and _settings.PUBLIC_URL:
            ok, resp = _telegram_set_webhook(_settings.PUBLIC_URL, _settings.TELEGRAM_BOT_TOKEN, _settings.TELEGRAM_SECRET_TOKEN)
            logger.info("setWebhook(%s/telegram) → ok=%s resp=%s", _settings.PUBLIC_URL, ok, resp)
            ok2, info = _telegram_get_webhook_info(_settings.TELEGRAM_BOT_TOKEN)
            logger.info("getWebhookInfo → ok=%s info=%s", ok2, info)
    except Exception as e:
        logger.warning("setWebhook skipped: %s", e)


@app.get("/healthz")
def healthz():
    # Минимальная проверка «живости»: конфиг загрузился
    return JSONResponse({"ok": bool(_settings), "symbol": getattr(_settings, "SYMBOL", None)})


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    # Простые метрики (без зависимостей от prometheus_client)
    lines = [
        f"app_up 1",
        f"bot_initialized {1 if _bot else 0}",
        f"exchange_initialized {1 if _exchange else 0}",
    ]
    return "\n".join(lines) + "\n"


@app.get("/config")
def show_config():
    hidden = {"TELEGRAM_BOT_TOKEN"}  # токен не светим в JSON полностью
    if not _settings:
        return JSONResponse({"ok": False, "error": "settings not initialized"})
    data = _safe_settings_dump(_settings)
    for k in list(data.keys()):
        if k in hidden:
            data[k] = "***"
    return JSONResponse(data)


@app.post("/telegram")
async def telegram_webhook(request: Request):
    """
    Вебхук для Telegram:
    - проверяем секрет из заголовка X-Telegram-Bot-Api-Secret-Token;
    - пробрасываем апдейт в telegram.bot.process_update(payload).
    """
    if not _settings:
        return Response(status_code=503)

    # проверка секрета (если задан)
    secret = _settings.TELEGRAM_SECRET_TOKEN
    if secret:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if header != secret:
            return Response(status_code=401)

    payload = await request.json()

    # Совместимость: process_update может быть sync/async
    try:
        if tgbot and hasattr(tgbot, "process_update"):
            res = tgbot.process_update(payload)  # type: ignore[attr-defined]
            if hasattr(res, "__await__"):
                await res  # если корутина
    except Exception as e:
        logger.exception("telegram.process_update failed: %s", e)

    return Response(status_code=204)
