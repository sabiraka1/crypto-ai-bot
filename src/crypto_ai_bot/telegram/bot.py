# -*- coding: utf-8 -*-
"""
Telegram command layer (webhook-friendly), curated and production-oriented.

Path: src/crypto_ai_bot/telegram/bot.py
"""

from __future__ import annotations

import io
import os
import time
import json
import math
import textwrap
from typing import Any, Dict, List, Optional, Tuple

import requests

# графики
import matplotlib
matplotlib.use("Agg")  # безопасный backend для Railway
import matplotlib.pyplot as plt

import numpy as np
import pandas as pd

# ccxt для данных/тикеров
try:
    import ccxt
except Exception:
    ccxt = None  # будем аккуратно проверять

# Трейдинговый движок
try:
    from crypto_ai_bot.trading.bot import get_bot, Settings
except Exception:
    from crypto_ai_bot.trading.bot import get_bot, Settings  # type: ignore

# Агрегатор признаков
try:
    from crypto_ai_bot.trading.signals.signal_aggregator import aggregate_features
except Exception:
    aggregate_features = None

START_TS = time.time()

def _bot_token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")
    return token

def _tg_api(method: str) -> str:
    return f"https://api.telegram.org/bot{_bot_token()}/{method}"

def _send_message(chat_id: int | str, text: str, *, parse_mode: str = "HTML", disable_web_page_preview: bool = True) -> None:
    try:
        requests.post(_tg_api("sendMessage"), json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }, timeout=12)
    except Exception:
        pass

def _send_photo(chat_id: int | str, png_bytes: bytes, caption: str = "") -> None:
    try:
        files = {"photo": ("chart.png", png_bytes, "image/png")}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        requests.post(_tg_api("sendPhoto"), files=files, data=data, timeout=20)
    except Exception:
        pass

# ======================= Exchange / data helpers =======================

_EXCHANGE: Optional[Any] = None

def _ensure_exchange():
    global _EXCHANGE
    if _EXCHANGE is not None:
        return _EXCHANGE
    if ccxt is None:
        return None
    name = os.getenv("EXCHANGE_NAME", "gateio")
    cls = getattr(ccxt, name, None)
    if cls is None:
        return None
    api_key = os.getenv("API_KEY") or os.getenv("GATE_API_KEY") or ""
    api_secret = os.getenv("API_SECRET") or os.getenv("GATE_API_SECRET") or ""
    params = {}
    if api_key and api_secret:
        params["apiKey"] = api_key
        params["secret"] = api_secret
    try:
        _EXCHANGE = cls(params)
        _EXCHANGE.userAgents = {'http': 'crypto-ai-bot/1.0'}
        _EXCHANGE.timeout = 10000
    except Exception:
        _EXCHANGE = None
    return _EXCHANGE

def _get_cfg():
    try:
        return Settings.build()
    except Exception:
        class _Dummy: pass
        return _Dummy()

def _fmt_dur(sec: float) -> str:
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s and not parts: parts.append(f"{s}s")
    return " ".join(parts) or "0s"

# ======================= Charts =======================

def _plot_price_chart(df: pd.DataFrame, *, title: str = "Price") -> bytes:
    fig = plt.figure(figsize=(8.5, 4.2), dpi=120)
    ax = fig.add_subplot(111)
    ax.plot(df["time"], df["close"], label="Close")
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    ax.plot(df["time"], ema20, label="EMA20")
    ax.plot(df["time"], ema50, label="EMA50")
    ax.set_title(title)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()

def _plot_rsi(df: pd.DataFrame) -> bytes:
    close = df["close"].to_numpy()
    diff = np.diff(close, prepend=close[0])
    gain = np.clip(diff, 0, None)
    loss = np.clip(-diff, 0, None)
    period = 14
    def _sma(x, n):
        s = pd.Series(x).rolling(n, min_periods=1).mean().to_numpy()
        return s
    avg_gain = _sma(gain, period)
    avg_loss = _sma(loss, period)
    rs = np.divide(avg_gain, avg_loss, out=np.full_like(avg_gain, np.inf), where=avg_loss!=0)
    rsi = 100 - (100 / (1 + rs))

    fig = plt.figure(figsize=(8.5, 2.5), dpi=120)
    ax = fig.add_subplot(111)
    ax.plot(df["time"], rsi, label="RSI(14)")
    ax.axhline(70, linestyle="--", linewidth=1)
    ax.axhline(30, linestyle="--", linewidth=1)
    ax.grid(True, alpha=0.25)
    ax.set_ylim(0, 100)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()

def _help_text() -> str:
    return textwrap.dedent("""\
        <b>Команды бота</b>

        <b>Основные</b>
        /status — краткий обзор: цена, индикаторы, позиция
        /chart [SYMBOL] [TF] — график цены + EMA20/50 (напр. /chart BTC/USDT 15m)
        /profit — сводка PnL, /profit_chart — график PnL
        /orders — последние ордера, /positions — открытые позиции
        /close — закрыть текущую позицию
        /testbuy &lt;USDT&gt; — тестовая покупка (paper/live в зависимости от cfg)
        /testsell &lt;USDT&gt; — тестовая продажа

        <b>Риск и настройки</b>
        /risk — активные гейты и факты с рынка (спред/объём/часы)
        /limits — торговые лимиты и ключевые пороги
        /config — текущий конфиг (символ, TF, режимы)
        /version — версия, /ping — аптайм и готовность

        <b>Сервис</b>
        /setwebhook — установить вебхук, /getwebhook — проверить, /delwebhook — удалить
    """).strip()

def _fmt_indicators(features: Dict) -> str:
    ind = features.get("indicators") or {}
    mkt = features.get("market") or {}
    price = ind.get("price")
    rs = features.get("rule_score")
    ai = os.getenv("AI_FAILOVER_SCORE", "0.55")
    atr_pct = ind.get("atr_pct")
    cond = mkt.get("condition", "neutral")
    return f"ℹ️ <b>{price:.2f}</b> | rule={rs:.2f} | ai={ai} | ATR%≈{atr_pct:.2f} | <i>{cond}</i>"

def _load_orders_csv(path: str, limit: int = 10) -> List[List[str]]:
    if not os.path.exists(path):
        return []
    import csv
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.reader(f):
            rows.append(row)
    return rows[-limit:]

def _load_positions_json(path: str) -> List[Dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("open", [])
    except Exception:
        return []

def _cmd_ping(chat_id: int, *_):
    uptime = _fmt_dur(time.time() - START_TS)
    _send_message(chat_id, f"✅ Online • uptime <b>{uptime}</b>")

def _cmd_help(chat_id: int, *_):
    _send_message(chat_id, _help_text())

def _cmd_version(chat_id: int, *_):
    _send_message(chat_id, "version: <b>1.0.0</b>")

def _cmd_config(chat_id: int, *_):
    cfg = _get_cfg()
    info = (
        f"SYMBOL={getattr(cfg,'SYMBOL','BTC/USDT')} TIMEFRAME={getattr(cfg,'TIMEFRAME','15m')}\n"
        f"ENABLE_TRADING={getattr(cfg,'ENABLE_TRADING',1)} SAFE_MODE={getattr(cfg,'SAFE_MODE',1)} PAPER_MODE={getattr(cfg,'PAPER_MODE',1)}\n"
        f"AI_MIN_TO_TRADE={getattr(cfg,'AI_MIN_TO_TRADE',0.55)} MIN_SCORE_TO_BUY={getattr(cfg,'MIN_SCORE_TO_BUY',0.65)}\n"
        f"USE_CONTEXT_PENALTIES={getattr(cfg,'USE_CONTEXT_PENALTIES',0)} CTX_CLAMP=[{getattr(cfg,'CTX_SCORE_CLAMP_MIN',0.0)},{getattr(cfg,'CTX_SCORE_CLAMP_MAX',1.0)}]"
    )
    _send_message(chat_id, f"<b>Config (Settings)</b>\n<code>{info}</code>")

def _cmd_status(chat_id: int, args: List[str]):
    cfg = _get_cfg()
    symbol = args[0] if args else getattr(cfg, "SYMBOL", "BTC/USDT")
    tf = args[1] if len(args) > 1 else getattr(cfg, "TIMEFRAME", "15m")

    ex = _ensure_exchange()
    if aggregate_features is None or ex is None:
        _send_message(chat_id, "❌ Не могу получить данные (нет биржи/агрегатора)")
        return

    feat = aggregate_features(cfg, ex, symbol=symbol, limit=int(getattr(cfg,"AGGREGATOR_LIMIT",200)))
    if isinstance(feat, dict) and "error" in feat:
        _send_message(chat_id, "❌ Нет данных для анализа")
        return

    text = f"💬 <b>{symbol} {tf}</b>\n" + _fmt_indicators(feat)
    pos_list = _load_positions_json(getattr(cfg,"PAPER_POSITIONS_FILE","paper_positions.json"))
    pos_emoji = "•".join("🟢" if (p.get('side')=='buy') else "🔴" for p in pos_list) or "—"
    text += f"\nПозиции: {pos_emoji} @ {feat.get('indicators',{}).get('price'):.2f}"
    _send_message(chat_id, text)

def _cmd_chart(chat_id: int, args: List[str]):
    cfg = _get_cfg()
    symbol = args[0] if args else getattr(cfg, "SYMBOL", "BTC/USDT")
    tf = args[1] if len(args) > 1 else getattr(cfg, "TIMEFRAME", "15m")
    ex = _ensure_exchange()
    if ex is None:
        _send_message(chat_id, "❌ Биржа недоступна")
        return
    try:
        ohlcv = ex.fetch_ohlcv(symbol, timeframe=tf, limit=200) or []
        if not ohlcv:
            _send_message(chat_id, "❌ Нет данных для графика"); return
        df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["ts"], unit="ms")
        img1 = _plot_price_chart(df, title=f"{symbol} {tf}")
        _send_photo(chat_id, img1, caption=f"{symbol} {tf}")
    except Exception:
        _send_message(chat_id, "❌ Не удалось построить график")

def _cmd_profit(chat_id: int, *_):
    cfg = _get_cfg()
    pnl_csv = getattr(cfg, "PAPER_PNL_FILE", "paper_pnl.csv")
    if not os.path.exists(pnl_csv):
        _send_message(chat_id, "PnL: пока нет данных"); return
    import csv
    rows = []
    with open(pnl_csv, "r", encoding="utf-8") as f:
        for row in csv.reader(f):
            rows.append(row)
    if len(rows) <= 1:
        _send_message(chat_id, "PnL: пока нет данных"); return
    header, body = rows[0], rows[1:]
    idx_abs = header.index("pnl_abs") if "pnl_abs" in header else -1
    idx_pct = header.index("pnl_pct") if "pnl_pct" in header else -1
    s_abs = sum(float(r[idx_abs]) for r in body if idx_abs >= 0)
    s_pct = sum(float(r[idx_pct]) for r in body if idx_pct >= 0)
    _send_message(chat_id, f"PnL: <b>{s_abs:.2f} USD</b> (sum pct ≈ {s_pct:.2f}%)")

def _cmd_profit_chart(chat_id: int, *_):
    cfg = _get_cfg()
    pnl_csv = getattr(cfg, "PAPER_PNL_FILE", "paper_pnl.csv")
    if not os.path.exists(pnl_csv):
        _send_message(chat_id, "Нет данных для графика"); return
    try:
        df = pd.read_csv(pnl_csv)
        if df.empty:
            _send_message(chat_id, "Нет данных для графика"); return
        df["t"] = pd.to_datetime(df["ts_close"])
        df["cum"] = df["pnl_abs"].cumsum()
        fig = plt.figure(figsize=(8.5, 3.2), dpi=120)
        ax = fig.add_subplot(111)
        ax.plot(df["t"], df["cum"], label="Cum PnL")
        ax.grid(True, alpha=0.25); ax.legend(loc="upper left", fontsize=8)
        fig.tight_layout()
        buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
        _send_photo(chat_id, buf.getvalue(), caption="График суммарного PnL")
    except Exception:
        _send_message(chat_id, "❌ Не удалось построить график PnL")

def _cmd_orders(chat_id: int, *_):
    cfg = _get_cfg()
    rows = _load_orders_csv(getattr(cfg,"PAPER_ORDERS_FILE","paper_orders.csv"), limit=10)
    if len(rows) <= 1:
        _send_message(chat_id, "Ордеров пока нет"); return
    header, body = rows[0], rows[1:]
    msg = ["<b>Последние ордера</b>"]
    for r in body[-10:]:
        try:
            ts, sym, side, qty, price, tag, typ = r
            msg.append(f"• {ts} {sym} {side} {qty}@{price} <code>{typ}</code>")
        except Exception:
            continue
    _send_message(chat_id, "\n".join(msg))

def _cmd_positions(chat_id: int, *_):
    cfg = _get_cfg()
    pos = _load_positions_json(getattr(cfg,"PAPER_POSITIONS_FILE","paper_positions.json"))
    if not pos:
        _send_message(chat_id, "Позиций нет"); return
    msg = ["<b>Открытые позиции</b>"]
    for p in pos:
        msg.append(f"• {p.get('symbol')} {p.get('side')} {p.get('qty')} @ {p.get('entry_price')}")
    _send_message(chat_id, "\n".join(msg))

def _cmd_close(chat_id: int, *_):
    ex = _ensure_exchange()
    bot = get_bot(exchange=ex, notifier=None, settings=_get_cfg())
    res = bot.request_close_position(source="telegram")
    text = res.get("message","ok") if isinstance(res, dict) else "ok"
    _send_message(chat_id, text)

def _cmd_test_order(chat_id: int, args: List[str], side: str):
    if not args:
        _send_message(chat_id, f"Использование: /test{side} &lt;USDT&gt;"); return
    try:
        amount = float(args[0])
    except Exception:
        _send_message(chat_id, "Сумма должна быть числом"); return
    ex = _ensure_exchange()
    bot = get_bot(exchange=ex, notifier=None, settings=_get_cfg())
    res = bot.request_market_order(side, amount, source="telegram")
    text = res.get("message","ok") if isinstance(res, dict) else "ok"
    _send_message(chat_id, text)

def _cmd_risk(chat_id: int, *_):
    cfg = _get_cfg()
    ex = _ensure_exchange()
    parts = [ "<b>Risk (гейты)</b>" ]
    parts.append(f"• MAX_SPREAD_BPS={getattr(cfg,'MAX_SPREAD_BPS',15)}")
    parts.append(f"• MIN_24H_VOLUME_USD={getattr(cfg,'MIN_24H_VOLUME_USD',1_000_000)}")
    parts.append(f"• HOURS={getattr(cfg,'TRADING_HOUR_START',0)}–{getattr(cfg,'TRADING_HOUR_END',24)} UTC")
    try:
        symbol = getattr(cfg, "SYMBOL", "BTC/USDT")
        spread_bps = None
        if ex and hasattr(ex, "fetch_order_book"):
            ob = ex.fetch_order_book(symbol, limit=5) or {}
            bid = float((ob.get("bids") or [[0]])[0][0])
            ask = float((ob.get("asks") or [[0]])[0][0])
            if bid and ask:
                spread_bps = (ask - bid) / ((ask + bid) / 2.0) * 10000.0
        if spread_bps is not None:
            parts.append(f"• Текущий спред ≈ {spread_bps:.1f} bps")
        if ex and hasattr(ex, "fetch_ticker"):
            t = ex.fetch_ticker(symbol) or {}
            vol = float(t.get("quoteVolume") or 0.0)
            if vol:
                parts.append(f"• 24h объём ≈ {vol:,.0f} USD")
    except Exception:
        pass
    _send_message(chat_id, "\n".join(parts))

def _cmd_limits(chat_id: int, *_):
    cfg = _get_cfg()
    parts = [
        "<b>Лимиты</b>",
        f"• TRADE_AMOUNT={getattr(cfg,'TRADE_AMOUNT',10)} USDT | MAX_CONCURRENT_POS={getattr(cfg,'MAX_CONCURRENT_POS',1)}",
        f"• SL={getattr(cfg,'STOP_LOSS_PCT',2.0)}%  TP={getattr(cfg,'TAKE_PROFIT_PCT',1.5)}%  TRAILING={getattr(cfg,'TRAILING_STOP_ENABLE',1)} @ {getattr(cfg,'TRAILING_STOP_PCT',0.5)}%",
        f"• MIN_SCORE_TO_BUY={getattr(cfg,'MIN_SCORE_TO_BUY',0.65)}  AI_MIN={getattr(cfg,'AI_MIN_TO_TRADE',0.55)}  GATE={getattr(cfg,'ENFORCE_AI_GATE',1)}",
        f"• ATR_PERIOD={getattr(cfg,'ATR_PERIOD',14)}  ATR_METHOD={getattr(cfg,'RISK_ATR_METHOD','ewm')}",
    ]
    _send_message(chat_id, "\n".join(parts))

def _cmd_setwebhook(chat_id: int, *_):
    url = os.getenv("PUBLIC_URL", "").rstrip("/") + "/telegram/webhook"
    secret = os.getenv("TELEGRAM_SECRET_TOKEN", "")
    data = {"url": url}
    if secret:
        data["secret_token"] = secret
    try:
        r = requests.post(_tg_api("setWebhook"), json=data, timeout=15).json()
    except Exception as e:
        r = {"ok": False, "error": str(e)}
    _send_message(chat_id, f"setWebhook → <code>{r}</code>")

def _cmd_getwebhook(chat_id: int, *_):
    try:
        r = requests.get(_tg_api("getWebhookInfo"), timeout=15).json()
    except Exception as e:
        r = {"ok": False, "error": str(e)}
    _send_message(chat_id, f"<code>{r}</code>")

def _cmd_delwebhook(chat_id: int, *_):
    try:
        r = requests.post(_tg_api("deleteWebhook"), json={}, timeout=15).json()
    except Exception as e:
        r = {"ok": False, "error": str(e)}
    _send_message(chat_id, f"deleteWebhook → <code>{r}</code>")

def _parse(text: str) -> Tuple[str, List[str]]:
    text = (text or "").strip()
    if not text.startswith("/"):
        return "", []
    parts = text.split()
    cmd = parts[0].lower()
    args = parts[1:]
    return cmd, args

def process_update(payload: Dict[str, Any]) -> None:
    try:
        message = payload.get("message") or payload.get("channel_post") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = message.get("text", "")
        if not chat_id or not text:
            return

        cmd, args = _parse(text)
        if cmd in ("/start", "/help"):
            _cmd_help(chat_id); return
        if cmd == "/ping":
            _cmd_ping(chat_id); return
        if cmd == "/version":
            _cmd_version(chat_id); return
        if cmd == "/config":
            _cmd_config(chat_id); return
        if cmd == "/status":
            _cmd_status(chat_id, args); return
        if cmd == "/chart":
            _cmd_chart(chat_id, args); return
        if cmd == "/profit":
            _cmd_profit(chat_id); return
        if cmd == "/profit_chart":
            _cmd_profit_chart(chat_id); return
        if cmd == "/orders":
            _cmd_orders(chat_id); return
        if cmd == "/positions":
            _cmd_positions(chat_id); return
        if cmd == "/close":
            _cmd_close(chat_id); return
        if cmd == "/testbuy":
            _cmd_test_order(chat_id, args, "buy"); return
        if cmd == "/testsell":
            _cmd_test_order(chat_id, args, "sell"); return
        if cmd == "/risk":
            _cmd_risk(chat_id); return
        if cmd == "/limits":
            _cmd_limits(chat_id); return
        if cmd == "/setwebhook":
            _cmd_setwebhook(chat_id); return
        if cmd == "/getwebhook":
            _cmd_getwebhook(chat_id); return
        if cmd == "/delwebhook":
            _cmd_delwebhook(chat_id); return

        _send_message(chat_id, "Неизвестная команда.\n\n" + _help_text())
    except Exception:
        pass
