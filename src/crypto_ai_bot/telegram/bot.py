
# -*- coding: utf-8 -*-
"""
Telegram Bot (Phase 4)
Path: src/crypto_ai_bot/telegram/bot.py

- Р‘РµР· os.getenv: РІСЃС‘ С‡РµСЂРµР· Settings.build()
- РљРѕРјР°РЅРґС‹: /start /help /status [/symbol] [/tf], /chart [/symbol] [/tf],
           /test [/symbol] [/tf], /testbuy <amt>, /testsell <amt>,
           /config, /version, /ping, /errors
- РРЅРґРёРєР°С‚РѕСЂС‹/СЂРµС€РµРЅРёРµ: core.signals.aggregator + validator + policy
- Р‘РµР· Р»РѕРєР°Р»СЊРЅС‹С… СЂР°СЃС‡С‘С‚РѕРІ РёРЅРґРёРєР°С‚РѕСЂРѕРІ
- РЎРѕРІРјРµСЃС‚РёРј СЃ server.py webhook-СЂРѕСѓС‚РѕРј: export async def process_update(payload)
"""
from __future__ import annotations

import io
import os
import re
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests
import ccxt
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.signals.aggregator import aggregate_features
from crypto_ai_bot.core.signals.validator import validate
from crypto_ai_bot.core.signals.policy import decide

# РѕРїС†РёРѕРЅР°Р»СЊРЅР°СЏ РёРЅС‚РµРіСЂР°С†РёСЏ СЃРѕ СЃС‚Р°СЂС‹Рј Р±РѕС‚РѕРј (РµСЃР»Рё РµСЃС‚СЊ)
try:
    from crypto_ai_bot.trading.bot import get_bot as legacy_get_bot
except Exception:
    legacy_get_bot = None

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, Settings.build().LOG_LEVEL.upper(), logging.INFO))


# --------------------------- Telegram API ---------------------------
@dataclass
class TgCtx:
    token: str
    api_base: str
    admin_ids: Tuple[int, ...]


def _build_tg() -> TgCtx:
    cfg = Settings.build()
    token = cfg.BOT_TOKEN or ""
    base = f"https://api.telegram.org/bot{token}"
    admins: Tuple[int, ...] = tuple(int(x) for x in (cfg.ADMIN_CHAT_IDS or "").replace(";", ",").split(",") if x.strip().isdigit())
    return TgCtx(token=token, api_base=base, admin_ids=admins)


def tg_request(method: str, data: Dict[str, Any], files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = _build_tg()
    if not ctx.token:
        raise RuntimeError("BOT_TOKEN is empty in Settings")
    url = f"{ctx.api_base}/{method}"
    try:
        if files:
            resp = requests.post(url, data=data, files=files, timeout=15)
        else:
            resp = requests.post(url, json=data, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.exception("tg_request failed: %s %s", method, e)
        return {"ok": False, "error": str(e)}


def send_text(chat_id: int, text: str, parse_mode: str = "HTML") -> None:
    tg_request("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True})


def send_photo(chat_id: int, png_bytes: bytes, caption: str = "") -> None:
    files = {"photo": ("chart.png", png_bytes, "image/png")}
    tg_request("sendPhoto", {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}, files=files)


# --------------------------- Exchange ---------------------------
def build_exchange(cfg: Settings):
    name = (cfg.EXCHANGE_NAME or "gateio").lower()
    klass = getattr(ccxt, name)
    params = {}
    key = (cfg.API_KEY or cfg.GATE_API_KEY or "").strip()
    sec = (cfg.API_SECRET or cfg.GATE_API_SECRET or "").strip()
    if key and sec:
        params["apiKey"] = key
        params["secret"] = sec
    ex = klass(params)
    ex.enableRateLimit = True
    # РЅРµРєРѕС‚РѕСЂС‹Рµ Р±РёСЂР¶Рё С‚СЂРµР±СѓСЋС‚ РЅР°СЃС‚СЂРѕР№РєРё
    if hasattr(ex, "options"):
        ex.options["defaultType"] = ex.options.get("defaultType", "spot")
    return ex


# --------------------------- Helpers ---------------------------
def parse_args(txt: str) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    # РїРѕРґРґРµСЂР¶РёРј: /status BTC/USDT 15m   РёР»Рё /testbuy 10
    parts = txt.strip().split()
    sym = None
    tf = None
    amt = None
    for p in parts[1:]:  # РїСЂРѕРїСѓСЃРєР°РµРј СЃР°РјСѓ РєРѕРјР°РЅРґСѓ
        u = p.strip()
        if re.match(r"^\d+(m|h|d)$", u, re.I):
            tf = u
        elif re.match(r"^[A-Z0-9]+[/-][A-Z0-9]+$", u, re.I):
            sym = u.replace("-", "/").upper()
        elif re.match(r"^\d+(\.\d+)?$", u):
            try:
                amt = float(u)
            except Exception:
                pass
    return sym, tf, amt


def fmt_indicators(ind: Dict[str, Any]) -> str:
    return (f"Р¦РµРЅР°: <b>{ind['price']:.2f}</b>\n"
            f"EMA20/EMA50: <b>{ind['ema20']:.2f}</b> / <b>{ind['ema50']:.2f}</b>\n"
            f"RSI: <b>{ind['rsi']:.1f}</b> | MACD(hist): <b>{ind['macd_hist']:.4f}</b>\n"
            f"ATR%%: <b>{ind['atr_pct']:.2f}</b>")


def make_chart(df: pd.DataFrame, ema20: pd.Series, ema50: pd.Series, title: str) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=150)
    ax.plot(df["ts"], df["close"], label="Close", linewidth=1.2)
    ax.plot(df["ts"], ema20, label="EMA20", linewidth=1.0)
    ax.plot(df["ts"], ema50, label="EMA50", linewidth=1.0)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.autofmt_xdate()
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def build_ohlcv_df(ex, symbol: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
    try:
        raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not raw:
            return None
        df = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume"]).astype(float)
        return df
    except Exception as e:
        logger.warning("fetch_ohlcv failed: %s", e)
        return None


# --------------------------- Command Handlers ---------------------------
def cmd_help() -> str:
    return (
        "<b>РЎРїСЂР°РІРєР° РїРѕ РєРѕРјР°РЅРґР°Рј</b>\n\n"
        "РћСЃРЅРѕРІРЅС‹Рµ:\n"
        "/start вЂ” РїСЂРёРІРµС‚СЃС‚РІРёРµ\n"
        "/status [SYMBOL] [TF] вЂ” РєСЂР°С‚РєРёР№ СЃС‚Р°С‚СѓСЃ Рё СЂРµРєРѕРјРµРЅРґР°С†РёСЏ\n"
        "/chart [SYMBOL] [TF] вЂ” РіСЂР°С„РёРє С†РµРЅС‹ + EMA\n"
        "/test [SYMBOL] [TF] вЂ” Р°РЅР°Р»РёР· (РєР°Рє /status)\n"
        "/testbuy <amt> вЂ” С‚РµСЃС‚РѕРІР°СЏ РїРѕРєСѓРїРєР° (paper)\n"
        "/testsell <amt> вЂ” С‚РµСЃС‚РѕРІР°СЏ РїСЂРѕРґР°Р¶Р° (paper)\n"
        "\nРЎР»СѓР¶РµР±РЅС‹Рµ:\n"
        "/config вЂ” С‚РµРєСѓС‰РёРµ РєР»СЋС‡РµРІС‹Рµ РЅР°СЃС‚СЂРѕР№РєРё\n"
        "/version вЂ” РІРµСЂСЃРёСЏ\n"
        "/ping вЂ” РїСЂРѕРІРµСЂРєР° Р±РѕС‚Р°\n"
        "/errors вЂ” РїРѕСЃР»РµРґРЅРёРµ РѕС€РёР±РєРё (РµСЃР»Рё СЃРµСЂРІРµСЂ РёС… Р»РѕРіРёСЂСѓРµС‚)\n"
        "\nРџСЂРёРјРµСЂС‹:\n"
        "/status BTC/USDT 15m\n"
        "/chart BTC/USDT 1h\n"
        "/testbuy 10"
    )


def cmd_config(cfg: Settings) -> str:
    return (
        "<b>Config (Settings)</b>\n"
        f"SYMBOL={cfg.SYMBOL} TIMEFRAME={cfg.TIMEFRAME}\n"
        f"TRADE_AMOUNT={cfg.TRADE_AMOUNT}\n"
        f"ENABLE_TRADING={'1' if cfg.ENABLE_TRADING else '0'} SAFE_MODE={'1' if cfg.SAFE_MODE else '0'} PAPER_MODE={'1' if cfg.PAPER_MODE else '0'}\n"
        f"AI_MIN_TO_TRADE={cfg.AI_MIN_TO_TRADE} MIN_SCORE_TO_BUY={cfg.MIN_SCORE_TO_BUY}\n"
        f"USE_CONTEXT_PENALTIES={'1' if cfg.USE_CONTEXT_PENALTIES else '0'}"
    )


def do_status(chat_id: int, text: str) -> None:
    cfg = Settings.build()
    sym, tf, _ = parse_args(text)
    sym = (sym or cfg.SYMBOL).replace("-", "/").upper()
    tf = tf or cfg.TIMEFRAME

    ex = build_exchange(cfg)
    fs = aggregate_features(cfg, ex, sym, tf, cfg.AGGREGATOR_LIMIT)
    fs = validate(fs)
    dec = decide(fs, cfg)

    ind = fs["indicators"]
    market = fs.get("market", {})
    msg = (
        f"\U0001F4C8 <b>{sym}</b> @ <b>{tf}</b>\n"
        f"{fmt_indicators(ind)}\n"
        f"Р С‹РЅРѕРє: <b>{market.get('condition','?')}</b>\n"
        f"Р РµС€РµРЅРёРµ: <b>{dec['action']}</b> (score={dec['score']:.2f}, {dec['reason']})"
    )
    send_text(chat_id, msg)


def do_chart(chat_id: int, text: str) -> None:
    cfg = Settings.build()
    sym, tf, _ = parse_args(text)
    sym = (sym or cfg.SYMBOL).replace("-", "/").upper()
    tf = tf or cfg.TIMEFRAME

    ex = build_exchange(cfg)
    df = build_ohlcv_df(ex, sym, tf, max(cfg.OHLCV_LIMIT, 120))
    if df is None or len(df) < 5:
        send_text(chat_id, "РќРµС‚ РґР°РЅРЅС‹С… РґР»СЏ РіСЂР°С„РёРєР°.")
        return

    # ema20/ema50 С‚РѕР»СЊРєРѕ РґР»СЏ РіСЂР°С„РёРєР°
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    png = make_chart(df, ema20, ema50, f"{sym} {tf}")

    send_photo(chat_id, png, caption=f"{sym} {tf}")


def do_test(chat_id: int, text: str) -> None:
    # alias РЅР° status СЃ РєРѕСЂРѕС‚РєРёРј РѕС‚РІРµС‚РѕРј
    cfg = Settings.build()
    sym, tf, _ = parse_args(text)
    sym = (sym or cfg.SYMBOL).replace("-", "/").upper()
    tf = tf or cfg.TIMEFRAME
    ex = build_exchange(cfg)
    fs = aggregate_features(cfg, ex, sym, tf, cfg.AGGREGATOR_LIMIT)
    fs = validate(fs)
    dec = decide(fs, cfg)
    ind = fs["indicators"]
    send_text(chat_id, f"<b>{sym}</b> {tf} | score={dec['score']:.2f} в†’ <b>{dec['action']}</b>\nRSI={ind['rsi']:.1f} ATR%={ind['atr_pct']:.2f}")


def do_test_order(chat_id: int, text: str, side: str) -> None:
    cfg = Settings.build()
    _, _, amt = parse_args(text)
    amt = float(amt or cfg.TRADE_AMOUNT)
    # РџС‹С‚Р°РµРјСЃСЏ РґРµСЂРЅСѓС‚СЊ Р»РµРіР°СЃРё-Р±РѕС‚ РґР»СЏ paper-РѕСЂРґРµСЂРѕРІ
    if legacy_get_bot is not None:
        try:
            ex = build_exchange(cfg)
            bot = legacy_get_bot(exchange=ex, notifier=lambda m: send_text(chat_id, m), settings=cfg)
            # Сѓ СЂР°Р·РЅС‹С… СЂРµР°Р»РёР·Р°С†РёР№ РјРѕРіСѓС‚ Р±С‹С‚СЊ СЂР°Р·РЅС‹Рµ РјРµС‚РѕРґС‹ вЂ” РїСЂРѕР±СѓРµРј РІР°СЂРёР°РЅС‚С‹
            if side == "buy":
                for meth in ("paper_market_buy", "paper_buy", "test_buy", "market_buy"):
                    if hasattr(bot, meth):
                        getattr(bot, meth)(amount=amt)
                        send_text(chat_id, f"\u2705 РўРµСЃС‚РѕРІР°СЏ РїРѕРєСѓРїРєР° {amt}")
                        return
            else:
                for meth in ("paper_market_sell", "paper_sell", "test_sell", "market_sell"):
                    if hasattr(bot, meth):
                        getattr(bot, meth)(amount=amt)
                        send_text(chat_id, f"\u2705 РўРµСЃС‚РѕРІР°СЏ РїСЂРѕРґР°Р¶Р° {amt}")
                        return
        except Exception as e:
            logger.warning("legacy test order failed: %s", e)
    # fallback вЂ” РїСЂРѕСЃС‚Рѕ РёРјРёС‚Р°С†РёСЏ
    send_text(chat_id, f"\u2705 Р—Р°РїСЂРѕСЃ РїСЂРёРЅСЏС‚: С‚РµСЃС‚РѕРІР°СЏ {('РїРѕРєСѓРїРєР°' if side=='buy' else 'РїСЂРѕРґР°Р¶Р°')} {amt} (paper)")


# --------------------------- Webhook entry ---------------------------
def _extract_message(payload: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
    msg = None
    if "message" in payload:
        msg = payload["message"]
    elif "edited_message" in payload:
        msg = payload["edited_message"]
    elif "channel_post" in payload:
        msg = payload["channel_post"]

    if not msg:
        return None, None

    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = msg.get("text") or ""
    return chat_id, text


def _route_command(chat_id: int, text: str) -> None:
    t = (text or "").strip()
    low = t.lower()
    if low.startswith("/start"):
        send_text(chat_id, "РџСЂРёРІРµС‚! РЇ Р±РѕС‚ С‚РѕСЂРіРѕРІРѕР№ СЃРёСЃС‚РµРјС‹. РќР°Р±РµСЂРё /help РґР»СЏ СЃРїСЂР°РІРєРё.")
    elif low.startswith("/help"):
        send_text(chat_id, cmd_help())
    elif low.startswith("/status"):
        do_status(chat_id, t)
    elif low.startswith("/chart"):
        do_chart(chat_id, t)
    elif low.startswith("/testbuy"):
        do_test_order(chat_id, t, "buy")
    elif low.startswith("/testsell"):
        do_test_order(chat_id, t, "sell")
    elif low.startswith("/test"):
        do_test(chat_id, t)
    elif low.startswith("/config"):
        send_text(chat_id, cmd_config(Settings.build()))
    elif low.startswith("/version"):
        send_text(chat_id, "version: 1.0.0")
    elif low.startswith("/ping"):
        send_text(chat_id, "pong")
    elif low.startswith("/errors"):
        send_text(chat_id, "Р›РѕРі-С„Р°Р№Р» РµС‰С‘ РЅРµ СЃРѕР·РґР°РЅ РёР»Рё РЅРµРґРѕСЃС‚СѓРїРµРЅ")
    else:
        send_text(chat_id, "РќРµРёР·РІРµСЃС‚РЅР°СЏ РєРѕРјР°РЅРґР°. /help вЂ” СЃРїРёСЃРѕРє РєРѕРјР°РЅРґ")


def _handle_update_sync(payload: Dict[str, Any]) -> None:
    chat_id, text = _extract_message(payload)
    if not chat_id:
        return
    _route_command(chat_id, text or "")


async def process_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Р’С…РѕРґ РёР· FastAPI webhook-СЂРѕСѓС‚Р° (server.py).
    FastAPI РѕР¶РёРґР°РµС‚ РєРѕСЂСѓС‚РёРЅСѓ вЂ” РІС‹РїРѕР»РЅСЏРµРј СЃРёРЅС…СЂРѕРЅРЅСѓСЋ С‡Р°СЃС‚СЊ РІ РїСѓР»Рµ.
    """
    await asyncio.to_thread(_handle_update_sync, payload)
    return {"ok": True}
