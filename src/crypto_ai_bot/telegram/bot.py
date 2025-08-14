
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import io
import csv
import json
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Tuple

import requests

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    import pandas as pd
except Exception:
    pd = None

try:
    import ccxt
except Exception:
    ccxt = None

# Telegram ENV
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_IDS = os.getenv("ADMIN_CHAT_IDS") or os.getenv("CHAT_ID") or ""

# Defaults if Settings not imported
DEFAULTS = {
    "SYMBOL": os.getenv("SYMBOL", "BTC/USDT"),
    "TIMEFRAME": os.getenv("TIMEFRAME", "15m"),
    "TRADE_AMOUNT": float(os.getenv("TRADE_AMOUNT", "10")),
    "ENABLE_TRADING": int(os.getenv("ENABLE_TRADING", "1")),
    "SAFE_MODE": int(os.getenv("SAFE_MODE", "1")),
    "PAPER_MODE": int(os.getenv("PAPER_MODE", "1")),
    "AI_MIN_TO_TRADE": float(os.getenv("AI_MIN_TO_TRADE", "0.55")),
    "MIN_SCORE_TO_BUY": float(os.getenv("MIN_SCORE_TO_BUY", "0.65")),
    "USE_CONTEXT_PENALTIES": int(os.getenv("USE_CONTEXT_PENALTIES", "0")),
}

def _tg_request(method: str, params: Dict[str, Any] = None, files: Dict[str, Any] = None) -> Dict[str, Any]:
    if not BOT_TOKEN:
        return {"ok": False, "error": "no_token"}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        resp = requests.post(url, data=params or {}, files=files or None, timeout=15)
        if resp.headers.get("Content-Type","").startswith("application/json"):
            return resp.json()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send_telegram_message(text: str, chat_id: Optional[str] = None) -> None:
    chat_ids = [c.strip() for c in (chat_id or ADMIN_CHAT_IDS).split(",") if c.strip()]
    if not chat_ids: return
    for cid in chat_ids:
        _tg_request("sendMessage", {"chat_id": cid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})

def send_telegram_photo(caption: str, fig) -> None:
    chat_ids = [c.strip() for c in ADMIN_CHAT_IDS.split(",") if c.strip()]
    if not chat_ids: return
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    for cid in chat_ids:
        files = {"photo": ("chart.png", buf, "image/png")}
        _tg_request("sendPhoto", {"chat_id": cid, "caption": caption}, files=files)
    buf.close()

def _exchange() -> Any:
    if not ccxt: return None
    return ccxt.gateio({
        "apiKey": os.getenv("GATE_API_KEY") or os.getenv("API_KEY"),
        "secret": os.getenv("GATE_API_SECRET") or os.getenv("API_SECRET"),
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {"defaultType": "spot"}
    })

def _fetch_ohlcv(symbol: str, timeframe: str, limit: int = 200) -> List[List[float]]:
    ex = _exchange()
    if not ex: return []
    return ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

def _last_price(symbol: str) -> float:
    ex = _exchange()
    if not ex: return 0.0
    try:
        t = ex.fetch_ticker(symbol)
        return float(t.get("last") or t.get("close") or 0.0)
    except Exception:
        return 0.0

def _safe_read_csv(path: str) -> Optional["pd.DataFrame"]:
    if not pd or not os.path.exists(path): return None
    try:
        return pd.read_csv(path, engine="python", on_bad_lines="skip")
    except Exception:
        try:
            return pd.read_csv(path, engine="python", on_bad_lines="skip", sep=";")
        except Exception:
            return None

# -------------------- Commands --------------------
def cmd_config(chat_id: str):
    # Пытаемся показать реальные значения из Settings
    try:
        from crypto_ai_bot.trading.bot import Settings
        cfg = Settings.build()
        text = (
            "<b>Config (Settings)</b>\n"
            f"SYMBOL={cfg.SYMBOL} TIMEFRAME={cfg.TIMEFRAME} TRADE_AMOUNT={cfg.TRADE_AMOUNT}\n"
            f"ENABLE_TRADING={cfg.ENABLE_TRADING} SAFE_MODE={cfg.SAFE_MODE} PAPER_MODE={cfg.PAPER_MODE}\n"
            f"AI_MIN_TO_TRADE={cfg.AI_MIN_TO_TRADE} MIN_SCORE_TO_BUY={cfg.MIN_SCORE_TO_BUY}\n"
            f"USE_CONTEXT_PENALTIES={cfg.USE_CONTEXT_PENALTIES} CTX_CLAMP=[{cfg.CTX_SCORE_CLAMP_MIN},{cfg.CTX_SCORE_CLAMP_MAX}]"
        )
        send_telegram_message(text, chat_id)
    except Exception:
        text = (
            "<b>Config (ENV)</b>\n"
            f"SYMBOL={DEFAULTS['SYMBOL']} TIMEFRAME={DEFAULTS['TIMEFRAME']} TRADE_AMOUNT={DEFAULTS['TRADE_AMOUNT']}\n"
            f"ENABLE_TRADING={DEFAULTS['ENABLE_TRADING']} SAFE_MODE={DEFAULTS['SAFE_MODE']} PAPER_MODE={DEFAULTS['PAPER_MODE']}\n"
            f"AI_MIN_TO_TRADE={DEFAULTS['AI_MIN_TO_TRADE']} MIN_SCORE_TO_BUY={DEFAULTS['MIN_SCORE_TO_BUY']}\n"
            f"USE_CONTEXT_PENALTIES={DEFAULTS['USE_CONTEXT_PENALTIES']}"
        )
        send_telegram_message(text, chat_id)

# Keep rest minimal for this diff; other commands can be from earlier version
def cmd_alive(chat_id: str): send_telegram_message("alive: ✅", chat_id)
def cmd_ping(chat_id: str): send_telegram_message("pong", chat_id)
def cmd_version(chat_id: str): send_telegram_message(f"version: {os.getenv('APP_VERSION','1.0.0')}", chat_id)

def _parse_command(text: str) -> Tuple[str, List[str]]:
    if not text: return "", []
    parts = text.strip().split(); cmd = parts[0].lower()
    if cmd.startswith("/"): cmd = cmd[1:]
    return cmd, parts[1:]

def _dispatch(chat_id: str, cmd: str, args: List[str]):
    if   cmd in ("config",): return cmd_config(chat_id)
    elif cmd in ("alive",): return cmd_alive(chat_id)
    elif cmd in ("ping",): return cmd_ping(chat_id)
    elif cmd in ("version","v"): return cmd_version(chat_id)
    else: return send_telegram_message("Unknown. Try /config /alive /ping /version", chat_id)

async def process_update(payload: Dict[str, Any]) -> None:
    try:
        message = payload.get("message") or payload.get("edited_message") or payload.get("callback_query", {}).get("message") or {}
        chat = message.get("chat", {})
        chat_id = str(chat.get("id") or ADMIN_CHAT_IDS or "")
        text = ""
        if "text" in message:
            text = message["text"]
        elif payload.get("callback_query", {}).get("data"):
            text = payload["callback_query"]["data"]
        if not chat_id: return
        cmd, args = _parse_command(text)
        if not cmd: return
        _dispatch(chat_id, cmd, args)
    except Exception as e:
        send_telegram_message(f"process_update error: {e}\n{traceback.format_exc()[:400]}")
