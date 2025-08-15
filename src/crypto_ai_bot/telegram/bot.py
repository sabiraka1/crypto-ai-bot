
# Clean Telegram adapter for webhook-based updates.
# Uses core Settings and the unified TradingBot entrypoint.
from __future__ import annotations

import os
import json
import time
import math
import logging
from typing import Any, Dict, Optional

import requests

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.trading.bot import get_bot

logger = logging.getLogger("telegram")
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))

CFG = Settings.build()

TELEGRAM_BASE = "https://api.telegram.org"
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID") or (os.getenv("ADMIN_CHAT_IDS", "").split(",")[0] if os.getenv("ADMIN_CHAT_IDS") else None)

def _tg_url(method: str) -> str:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    return f"{TELEGRAM_BASE}/bot{BOT_TOKEN}/{method}"

def tg_send_message(chat_id: str, text: str, **kwargs) -> None:
    try:
        url = _tg_url("sendMessage")
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", **kwargs}
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        logger.warning("tg_send_message error: %s", e)

def tg_reply(update: Dict[str, Any], text: str, **kwargs) -> None:
    chat_id = CHAT_ID
    # Try to use chat from update if available
    try:
        chat_id = update["message"]["chat"]["id"]
    except Exception:
        pass
    if chat_id:
        tg_send_message(str(chat_id), text, **kwargs)

def _help_text() -> str:
    return (
        "<b>Ğ¡Ğ¿Ñ€Ğ°Ğ²ĞºĞ° Ğ¿Ğ¾ ĞºĞ¾Ğ¼Ğ°Ğ½Ğ´Ğ°Ğ¼</b>\n\n"
        "ĞÑĞ½Ğ¾Ğ²Ğ½Ñ‹Ğµ:\n"
        "/start â€” Ğ¿Ñ€Ğ¸Ğ²ĞµÑ‚ÑÑ‚Ğ²Ğ¸Ğµ\n"
        "/status â€” Ñ†ĞµĞ½Ğ°/Ğ¸Ğ½Ğ´Ğ¸ĞºĞ°Ñ‚Ğ¾Ñ€Ñ‹/Ğ¿Ğ¾Ğ·Ğ¸Ñ†Ğ¸Ñ\n"
        "/chart â€” Ğ³Ñ€Ğ°Ñ„Ğ¸Ğº (ÑƒĞ¿Ñ€Ğ¾Ñ‰Ñ‘Ğ½Ğ½Ğ¾)\n"
        "/errors â€” Ğ¿Ğ¾ÑĞ»ĞµĞ´Ğ½Ğ¸Ğµ Ğ¾ÑˆĞ¸Ğ±ĞºĞ¸\n"
        "/config â€” Ñ‚ĞµĞºÑƒÑ‰Ğ°Ñ ĞºĞ¾Ğ½Ñ„Ğ¸Ğ³ÑƒÑ€Ğ°Ñ†Ğ¸Ñ\n"
        "/ping â€” Ğ¿Ñ€Ğ¾Ğ²ĞµÑ€ĞºĞ° ÑĞ²ÑĞ·Ğ¸\n"
        "/version â€” Ğ²ĞµÑ€ÑĞ¸Ñ\n\n"
        "Ğ¢Ñ€ĞµĞ¹Ğ´Ğ¸Ğ½Ğ³:\n"
        "/testbuy &lt;ÑÑƒĞ¼Ğ¼Ğ°&gt; â€” Ñ‚ĞµÑÑ‚Ğ¾Ğ²Ğ°Ñ Ğ¿Ğ¾ĞºÑƒĞ¿ĞºĞ°\n"
        "/testsell â€” Ñ‚ĞµÑÑ‚Ğ¾Ğ²Ğ°Ñ Ğ¿Ñ€Ğ¾Ğ´Ğ°Ğ¶Ğ°/Ğ·Ğ°ĞºÑ€Ñ‹Ñ‚Ğ¸Ğµ\n\n"
        "Ğ¡ĞµÑ€Ğ²Ğ¸Ñ:\n"
        "/setwebhook, /getwebhook, /delwebhook â€” ÑƒĞ¿Ñ€Ğ°Ğ²Ğ»ĞµĞ½Ğ¸Ğµ Ğ²ĞµĞ±Ñ…ÑƒĞºĞ¾Ğ¼\n"
    )

def _format_config(cfg: Settings) -> str:
    fields = [
        ("SYMBOL", cfg.SYMBOL),
        ("TIMEFRAME", cfg.TIMEFRAME),
        ("TRADE_AMOUNT", cfg.TRADE_AMOUNT),
        ("ENABLE_TRADING", cfg.ENABLE_TRADING),
        ("SAFE_MODE", cfg.SAFE_MODE),
        ("PAPER_MODE", cfg.PAPER_MODE),
        ("AI_ENABLE", cfg.AI_ENABLE),
        ("MIN_SCORE_TO_BUY", cfg.MIN_SCORE_TO_BUY),
    ]
    lines = [f"{k}={v}" for k, v in fields]
    return "<b>Config (Settings)</b>\n" + "\n".join(lines)

def _format_status() -> str:
    try:
        bot = get_bot(exchange=None, notifier=None, settings=CFG)
        # ĞŸĞ¾Ğ¿Ñ€Ğ¾Ğ±ÑƒĞµĞ¼ Ğ¿Ğ¾Ğ»ÑƒÑ‡Ğ¸Ñ‚ÑŒ Ğ¿Ğ¾ÑĞ»ĞµĞ´Ğ½Ğ¸Ğµ Ñ„Ğ¸Ñ‡Ğ¸ (Ğ±ĞµĞ· Ğ¿Ğ°Ğ´ĞµĞ½Ğ¸Ñ, ĞµÑĞ»Ğ¸ Ğ½ĞµÑ‚ Ğ´Ğ°Ğ½Ğ½Ñ‹Ñ…)
        try:
            features = bot.aggregate_features()
            rsi = features.get("rsi")
            atr = features.get("atr")
            rule = round(features.get("rule_score", 0), 2)
            ai = round(features.get("ai_score", 0), 2)
        except Exception:
            rsi = None; atr = None; rule = 0; ai = 0
        price = getattr(bot, "last_price", None) or (features.get("price") if 'features' in locals() else None)
        trend = "bullish" if rule >= 0.55 else "bearish"
        parts = [f"â„¹ï¸ {CFG.SYMBOL} @ {price or 'â€”'} | rule={rule} | ai={ai} | ATR%â‰ˆ{round(atr or 0, 2) if atr else 'â€”'} | {trend}"]
        return "\n".join(parts)
    except Exception as e:
        logger.exception("status error")
        return f"ĞÑˆĞ¸Ğ±ĞºĞ° ÑÑ‚Ğ°Ñ‚ÑƒÑĞ°: {e}"

def _with_public_url() -> Optional[str]:
    public_url = os.getenv("PUBLIC_URL") or ""
    if not public_url:
        return None
    if not public_url.startswith("http"):
        public_url = "https://" + public_url
    return public_url.rstrip("/")

def _set_webhook() -> str:
    public = _with_public_url()
    if not public:
        return "PUBLIC_URL Ğ½Ğµ Ğ·Ğ°Ğ´Ğ°Ğ½."
    secret = os.getenv("TELEGRAM_SECRET_TOKEN", "")
    url = _tg_url("setWebhook")
    hook = f"{public}/telegram/webhook"
    resp = requests.post(url, json={
        "url": hook,
        **({"secret_token": secret} if secret else {})
    }, timeout=10).json()
    return f"setWebhook â†’ {resp}"

def _get_webhook() -> str:
    url = _tg_url("getWebhookInfo")
    try:
        resp = requests.get(url, timeout=10).json()
    except Exception as e:
        resp = {"ok": False, "error": str(e)}
    return json.dumps(resp, ensure_ascii=False)

def _del_webhook() -> str:
    url = _tg_url("deleteWebhook")
    try:
        resp = requests.post(url, json={"drop_pending_updates": False}, timeout=10).json()
    except Exception as e:
        resp = {"ok": False, "error": str(e)}
    return f"deleteWebhook â†’ {resp}"

def _cmd_testbuy(args: str) -> str:
    try:
        amt = float(args.strip() or "0")
        if amt <= 0: 
            return "Ğ£ĞºĞ°Ğ¶Ğ¸ ÑÑƒĞ¼Ğ¼Ñƒ: /testbuy 10"
        bot = get_bot(exchange=None, notifier=None, settings=CFG)
        try:
            bot.request_market_order("buy", amt)
            return f"âœ… Ğ—Ğ°ÑĞ²ĞºĞ° Ğ½Ğ° Ğ¿Ğ¾ĞºÑƒĞ¿ĞºÑƒ Ğ¾Ñ‚Ğ¿Ñ€Ğ°Ğ²Ğ»ĞµĞ½Ğ°: {amt}"
        except Exception as e:
            return f"ĞÑˆĞ¸Ğ±ĞºĞ° Ğ¾Ñ‚Ğ¿Ñ€Ğ°Ğ²ĞºĞ¸ Ğ·Ğ°ÑĞ²ĞºĞ¸: {e}"
    except Exception:
        return "Ğ¤Ğ¾Ñ€Ğ¼Ğ°Ñ‚: /testbuy 10"

def _cmd_testsell(_args: str) -> str:
    try:
        bot = get_bot(exchange=None, notifier=None, settings=CFG)
        try:
            bot.request_close_position()
            return "âœ… Ğ—Ğ°ÑĞ²ĞºĞ° Ğ½Ğ° Ğ·Ğ°ĞºÑ€Ñ‹Ñ‚Ğ¸Ğµ Ğ¿Ğ¾Ğ·Ğ¸Ñ†Ğ¸Ğ¸ Ğ¾Ñ‚Ğ¿Ñ€Ğ°Ğ²Ğ»ĞµĞ½Ğ°"
        except Exception as e:
            return f"ĞÑˆĞ¸Ğ±ĞºĞ° Ğ¾Ñ‚Ğ¿Ñ€Ğ°Ğ²ĞºĞ¸ Ğ·Ğ°ÑĞ²ĞºĞ¸: {e}"
    except Exception as e:
        return f"ĞÑˆĞ¸Ğ±ĞºĞ°: {e}"

def _cmd_errors() -> str:
    log_dir = os.getenv("LOGS_DIR", "logs")
    path = os.path.join(log_dir, "app.log")
    if not os.path.exists(path):
        return "Ğ›Ğ¾Ğ³-Ñ„Ğ°Ğ¹Ğ» ĞµÑ‰Ñ‘ Ğ½Ğµ ÑĞ¾Ğ·Ğ´Ğ°Ğ½"
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-50:]
        return "<b>ĞŸĞ¾ÑĞ»ĞµĞ´Ğ½Ğ¸Ğµ Ğ¾ÑˆĞ¸Ğ±ĞºĞ¸/Ğ»Ğ¾Ğ³Ğ¸:</b>\n" + "".join(lines[-20:])[-3500:]
    except Exception as e:
        return f"ĞĞµ ÑƒĞ´Ğ°Ğ»Ğ¾ÑÑŒ Ğ¿Ñ€Ğ¾Ñ‡Ğ¸Ñ‚Ğ°Ñ‚ÑŒ Ğ»Ğ¾Ğ³Ğ¸: {e}"

def handle_update(update: Dict[str, Any]) -> None:
    # Sync handler â€” for invocation from FastAPI async wrapper
    try:
        if "message" not in update: 
            return
        text = update["message"].get("text") or ""
        if not text.startswith("/"):
            return
        cmd, *rest = text.split(" ", 1)
        args = rest[0] if rest else ""

        if cmd in ("/start", "/help"):
            tg_reply(update, _help_text())
        elif cmd == "/ping":
            tg_reply(update, "pong")
        elif cmd == "/config":
            tg_reply(update, _format_config(CFG))
        elif cmd == "/status":
            tg_reply(update, _format_status())
        elif cmd == "/errors":
            tg_reply(update, _cmd_errors())
        elif cmd == "/testbuy":
            tg_reply(update, _cmd_testbuy(args))
        elif cmd == "/testsell":
            tg_reply(update, _cmd_testsell(args))
        elif cmd == "/setwebhook":
            tg_reply(update, _set_webhook())
        elif cmd == "/getwebhook":
            tg_reply(update, _get_webhook())
        elif cmd == "/delwebhook":
            tg_reply(update, _del_webhook())
        else:
            tg_reply(update, "ĞĞµĞ¸Ğ·Ğ²ĞµÑÑ‚Ğ½Ğ°Ñ ĞºĞ¾Ğ¼Ğ°Ğ½Ğ´Ğ°. ĞĞ°Ğ¿Ğ¸ÑˆĞ¸ /help")
    except Exception as e:
        logger.exception("handle_update error: %s", e)

# FastAPI will call this
async def process_update(update: Dict[str, Any]) -> Dict[str, Any]:
    handle_update(update)
    return {"ok": True}

