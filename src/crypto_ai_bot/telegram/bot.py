# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Telegram Bot module
-------------------
Расширённый набор команд. Совместим с FastAPI-вебхуком, который вызывает process_update(payload).

Поддерживаются:
- /start /help /ping /alive /version
- /config        -> централизованный Settings
- /status        -> лайв-цена, ATR%, краткое состояние paper-позиции
- /profit        -> суммарный PnL
- /profit_chart  -> график PnL (matplotlib Agg)
- /errors        -> безопасный хвост CSV (on_bad_lines='skip')
- /orders        -> последние paper-ордера
- /positions     -> краткое состояние позиции
- /close         -> запрос движку закрыть позицию
- /chart [/test] -> график OHLCV+EMA20/50 (ccxt), /test — инфострока
- /train         -> обучение модели (analysis.sinyal_skorlayici.train_model)
- /setwebhook /getwebhook /delwebhook -> управление вебхуком (учитывает secret_token)
- /settrade key=val ...  -> апдейт части Settings на лету (до рестарта)
- /setrisk  key=val ...  -> то же для риск-параметров
- /metrics      -> ссылка на HTTP-метрики сервера
"""

import io
import json
import os
import time
from typing import Dict, Any, Optional, List, Tuple

import requests

# Matplotlib 'Agg' для headless-сервера
import matplotlib
matplotlib.use("Agg")  # noqa
import matplotlib.pyplot as plt  # type: ignore

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None

try:
    import numpy as np  # noqa
except Exception:  # pragma: no cover
    np = None

# Наши модули (с фоллбэками)
try:
    from crypto_ai_bot.trading.bot import get_bot, Settings  # централизованный конфиг и синглтон-бот
except Exception:
    get_bot = None
    Settings = None

try:
    from crypto_ai_bot.analysis.technical_indicators import calculate_all_indicators
except Exception:
    calculate_all_indicators = None

# Опционально: обучение
try:
    from crypto_ai_bot.analysis.sinyal_skorlayici import train_model as _train_model
except Exception:
    _train_model = None

# --- ENV ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_IDS = [s.strip() for s in (os.getenv("ADMIN_CHAT_IDS") or "").split(",") if s.strip()]
PUBLIC_URL = os.getenv("PUBLIC_URL")
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN")

PAPER_ORDERS_FILE = os.getenv("PAPER_ORDERS_FILE", "paper_orders.csv")
PAPER_POSITIONS_FILE = os.getenv("PAPER_POSITIONS_FILE", "paper_positions.json")
PAPER_PNL_FILE = os.getenv("PAPER_PNL_FILE", "paper_pnl.csv")
SIGNALS_CSV = os.getenv("SIGNALS_CSV", "signals_snapshots.csv")

# --- Telegram helpers ---
def _api_url(method: str) -> str:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

def _post(method: str, data: Dict[str, Any], files: Dict[str, Any] | None = None) -> Dict[str, Any]:
    try:
        resp = requests.post(_api_url(method), data=data, files=files, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send_telegram_message(chat_id: str | int, text: str, parse_mode: Optional[str] = None, disable_web_page_preview: bool = True) -> Dict[str, Any]:
    data = {"chat_id": chat_id, "text": text, "disable_web_page_preview": disable_web_page_preview}
    if parse_mode:
        data["parse_mode"] = parse_mode
    return _post("sendMessage", data)

def send_telegram_photo(chat_id: str | int, image_bytes: bytes, caption: Optional[str] = None) -> Dict[str, Any]:
    files = {"photo": ("chart.png", image_bytes)}
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
    return _post("sendPhoto", data=data, files=files)

# --- Utils ---
def _load_df_csv(path: str, n_tail: int = 25) -> Optional["pd.DataFrame"]:
    if pd is None or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, on_bad_lines="skip")
        return df.tail(n_tail) if n_tail else df
    except Exception:
        return None

def _read_positions_short(path: str) -> str:
    if not os.path.exists(path):
        return "Позиций нет"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return "Позиций нет"
        side = data.get("side", "-")
        amt = data.get("amount", 0)
        entry = data.get("entry_price", 0)
        return f"Позиция: {side} {amt} @ {entry}"
    except Exception:
        return "Позиции: ошибка чтения"

def _build_runtime_cfg_string(cfg) -> str:
    try:
        fields = [
            ("SYMBOL", cfg.SYMBOL), ("TIMEFRAME", cfg.TIMEFRAME), ("TRADE_AMOUNT", cfg.TRADE_AMOUNT),
            ("ENABLE_TRADING", cfg.ENABLE_TRADING), ("SAFE_MODE", cfg.SAFE_MODE), ("PAPER_MODE", cfg.PAPER_MODE),
            ("AI_MIN_TO_TRADE", getattr(cfg, "AI_MIN_TO_TRADE", None)),
            ("MIN_SCORE_TO_BUY", getattr(cfg, "MIN_SCORE_TO_BUY", None)),
            ("USE_CONTEXT_PENALTIES", getattr(cfg, "USE_CONTEXT_PENALTIES", None)),
            ("CTX_CLAMP", f"[{getattr(cfg,'CTX_SCORE_CLAMP_MIN',0.0)},{getattr(cfg,'CTX_SCORE_CLAMP_MAX',1.0)}]"),
        ]
        lines = [f"{k}={v}" for k, v in fields if v is not None]
        return "Config (Settings)\n" + " ".join(lines)
    except Exception:
        return "Config: недоступно (ошибка Settings)"

# --- Exchange / OHLCV ---
def _get_exchange():
    # Сначала пробуем реиспользовать exchange из синглтон-бота (rate limit общие)
    if get_bot is not None:
        try:
            bot = get_bot()
            if bot and getattr(bot, "exchange", None):
                return bot.exchange
        except Exception:
            pass
    # Фоллбэк: прямой ccxt.gateio из ENV
    try:
        import ccxt
        key = os.getenv("GATE_API_KEY") or os.getenv("API_KEY")
        secret = os.getenv("GATE_API_SECRET") or os.getenv("API_SECRET")
        ex = ccxt.gateio({
            "apiKey": key, "secret": secret,
            "enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "spot"}
        })
        return ex
    except Exception:
        return None

def _fetch_ohlcv(symbol: str, timeframe: str, limit: int = 200) -> Optional["pd.DataFrame"]:
    if pd is None:
        return None
    ex = _get_exchange()
    if ex is None:
        return None
    try:
        data = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(data, columns=["time","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df.set_index("time", inplace=True)
        return df
    except Exception:
        return None

# --- Charts ---
def _plot_ohlcv_with_indicators(df: "pd.DataFrame") -> bytes:
    if pd is None or df is None or df.empty:
        raise RuntimeError("Нет данных для графика")
    if calculate_all_indicators is None:
        raise RuntimeError("Модуль индикаторов недоступен")

    feats = calculate_all_indicators(df).dropna().copy()

    fig, ax = plt.subplots(figsize=(10, 5), dpi=140)
    ax.plot(feats.index, feats["close"], label="Close")
    ax.plot(feats.index, feats["ema20"], label="EMA20")
    ax.plot(feats.index, feats["ema50"], label="EMA50")
    ax.set_title("OHLCV + EMA(20/50)")
    ax.grid(True, alpha=0.3)
    ax.legend()

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.read()

# --- Commands ---
def _cmd_help() -> str:
    return (
        "Справка по командам:\n"
        "Основные: /start /help /ping /alive /version /config /status /chart\n"
        "Торговля: /profit /profit_chart /orders /positions /close\n"
        "Тест/индикаторы: /test [/chart]\n"
        "ML: /train\n"
        "Сервис: /errors /setwebhook /getwebhook /delwebhook /settrade /setrisk /metrics\n"
    )

def _cmd_status() -> str:
    sym = os.getenv("SYMBOL", "BTC/USDT")
    tf = os.getenv("TIMEFRAME", "15m")

    pos = _read_positions_short(PAPER_POSITIONS_FILE)

    ex = _get_exchange()
    try:
        price = ex.fetch_ticker(sym)["last"] if ex else None
    except Exception:
        price = None

    atr_pct = None
    try:
        df = _fetch_ohlcv(sym, tf, limit=100)
        if df is not None and not df.empty and calculate_all_indicators is not None:
            f = calculate_all_indicators(df).dropna()
            if not f.empty:
                atr_pct = (f["atr"].iloc[-1] / f["close"].iloc[-1]) * 100.0
    except Exception:
        pass

    parts = []
    if price is not None:
        parts.append(f"ℹ️ {sym} @ {price:,.2f}")
    if atr_pct is not None:
        parts.append(f"ATR%≈{atr_pct:.2f}")
    parts.append(pos)
    return " | ".join(parts)

def _cmd_profit() -> str:
    df = _load_df_csv(PAPER_PNL_FILE, n_tail=0)
    if df is None or df.empty:
        return "Профит: пока нет данных"
    try:
        pnl = float(df["pnl_usd"].sum())
        n = len(df)
        return f"PnL (paper): {pnl:+.2f} USD, закрытых сделок: {n}"
    except Exception:
        return "Профит: ошибка чтения"

def _cmd_profit_chart() -> Optional[bytes]:
    df = _load_df_csv(PAPER_PNL_FILE, n_tail=0)
    if df is None or df.empty:
        return None
    try:
        fig, ax = plt.subplots(figsize=(10, 5), dpi=140)
        equity = df["pnl_usd"].cumsum()
        ax.plot(equity.index, equity.values, label="Equity (cum PnL)")
        ax.set_title("Equity curve (paper)")
        ax.grid(True, alpha=0.3)
        ax.legend()
        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None

def _cmd_errors() -> str:
    df = _load_df_csv(SIGNALS_CSV, n_tail=20)
    if df is None:
        return "Лог-файл ещё не создан или недоступен"
    return "Последние записи:\n" + df.to_string(index=False)

def _cmd_orders() -> str:
    df = _load_df_csv(PAPER_ORDERS_FILE, n_tail=15)
    if df is None or df.empty:
        return "Заказы: пока нет"
    cols = [c for c in df.columns][:8]
    return "Последние ордера:\n" + df[cols].to_string(index=False)

def _cmd_positions() -> str:
    return _read_positions_short(PAPER_POSITIONS_FILE)

def _cmd_close() -> str:
    if get_bot is None:
        return "Бот недоступен"
    try:
        bot = get_bot()
        if not bot:
            return "Бот недоступен"
        res = bot.request_close_position() if hasattr(bot, "request_close_position") else None
        return "Запрос на закрытие отправлен" if res is not False else "Не удалось отправить запрос"
    except Exception:
        return "Ошибка закрытия позиции"

def _cmd_chart(args: List[str]) -> Tuple[Optional[bytes], str]:
    sym = os.getenv("SYMBOL", "BTC/USDT")
    tf = os.getenv("TIMEFRAME", "15m")
    if args:
        if len(args) >= 1:
            sym = args[0].upper().replace(":", "/")
        if len(args) >= 2:
            tf = args[1]
    df = _fetch_ohlcv(sym, tf, limit=200)
    if df is None or df.empty:
        return None, "Нет данных для графика"
    try:
        img = _plot_ohlcv_with_indicators(df)
        return img, f"{sym} {tf}"
    except Exception as e:
        return None, f"Ошибка графика: {e}"

def _cmd_test(args: List[str]) -> str:
    sym = os.getenv("SYMBOL", "BTC/USDT")
    tf = os.getenv("TIMEFRAME", "15m")
    if args:
        if len(args) >= 1:
            sym = args[0].upper().replace(":", "/")
        if len(args) >= 2:
            tf = args[1]
    df = _fetch_ohlcv(sym, tf, limit=120)
    if df is None or df.empty:
        return "Нет данных"
    try:
        feats = calculate_all_indicators(df).dropna() if calculate_all_indicators else df
        atrp = (feats["atr"].iloc[-1]/feats["close"].iloc[-1])*100.0 if "atr" in feats.columns else None
        ai = os.getenv("AI_MIN_TO_TRADE", "0.55")
        rule = os.getenv("MIN_SCORE_TO_BUY", "0.65")
        parts = [f"ℹ️ {sym} @ {feats['close'].iloc[-1]:,.2f}", f"rule={rule}", f"ai={ai}"]
        if atrp is not None:
            parts.append(f"ATR%≈{atrp:.2f}")
        return " | ".join(parts)
    except Exception:
        return "Ошибка теста"

def _cmd_train() -> str:
    if _train_model is None:
        return "Модуль обучения недоступен"
    try:
        msg = _train_model()
        return msg
    except Exception as e:
        return f"Ошибка обучения: {e}"

def _cmd_metrics_url() -> str:
    return f"{PUBLIC_URL}/metrics" if PUBLIC_URL else "Metrics URL неизвестен"

def _apply_runtime_updates(kind: str, kv_pairs: List[str]) -> str:
    """
    kind: 'trade' или 'risk'
    kv_pairs: ["KEY=VALUE", ...]
    """
    if get_bot is None or Settings is None:
        return "Settings недоступен"
    bot = get_bot()
    if not bot:
        return "Бот недоступен"
    cfg = getattr(bot, "settings", None)
    if not cfg:
        return "Config недоступен"

    changed = []
    for pair in kv_pairs:
        if "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        key = key.strip().upper()
        val = val.strip()
        # попытка привести тип
        parsed: Any = val
        if val.lower() in ("1","true","yes","on"):
            parsed = 1
        elif val.lower() in ("0","false","no","off"):
            parsed = 0
        else:
            try:
                parsed = float(val) if "." in val else int(val)
            except Exception:
                pass
        if hasattr(cfg, key):
            try:
                setattr(cfg, key, parsed)
                changed.append(f"{key}={parsed}")
            except Exception:
                pass
    return "Обновлено (до рестарта): " + (", ".join(changed) if changed else "ничего")

# --- Webhook dispatcher ---
def process_update(update: Dict[str, Any]) -> Dict[str, Any]:
    """
    Принимает Telegram update (dict). Возвращает {"ok": True}.
    """
    try:
        message = update.get("message") or update.get("edited_message") or {}
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()

        if not chat_id or not text:
            return {"ok": True}

        # Базовые
        if text.startswith("/start"):
            send_telegram_message(chat_id, "Привет! Команды: /help /config /status /chart /profit /train /errors /ping /version")
            return {"ok": True}

        if text.startswith("/help"):
            send_telegram_message(chat_id, _cmd_help())
            return {"ok": True}

        if text.startswith("/ping") or text.startswith("/alive"):
            send_telegram_message(chat_id, "pong")
            return {"ok": True}

        if text.startswith("/version"):
            send_telegram_message(chat_id, "version: 1.0.0")
            return {"ok": True}

        if text.startswith("/config"):
            if Settings is None:
                send_telegram_message(chat_id, "Settings недоступен")
            else:
                cfg = Settings.build()
                send_telegram_message(chat_id, _build_runtime_cfg_string(cfg))
            return {"ok": True}

        # Торговля/статусы
        if text.startswith("/status"):
            send_telegram_message(chat_id, _cmd_status())
            return {"ok": True}

        if text.startswith("/profit_chart"):
            img = _cmd_profit_chart()
            if img:
                send_telegram_photo(chat_id, img, caption="Equity (paper)")
            else:
                send_telegram_message(chat_id, "Нет данных для графика")
            return {"ok": True}

        if text.startswith("/profit"):
            send_telegram_message(chat_id, _cmd_profit())
            return {"ok": True}

        if text.startswith("/errors"):
            send_telegram_message(chat_id, _cmd_errors())
            return {"ok": True}

        if text.startswith("/orders"):
            send_telegram_message(chat_id, _cmd_orders())
            return {"ok": True}

        if text.startswith("/positions"):
            send_telegram_message(chat_id, _cmd_positions())
            return {"ok": True}

        if text.startswith("/close"):
            send_telegram_message(chat_id, _cmd_close())
            return {"ok": True}

        # Чарты/тест
        if text.startswith("/chart") or text.startswith("/test"):
            parts = text.split()
            args = parts[1:] if len(parts) > 1 else []
            if text.startswith("/chart"):
                img, cap = _cmd_chart(args)
                if img:
                    send_telegram_photo(chat_id, img, caption=cap)
                else:
                    send_telegram_message(chat_id, cap or "Ошибка графика")
            else:
                send_telegram_message(chat_id, _cmd_test(args))
            return {"ok": True}

        # Обучение
        if text.startswith("/train") or text.startswith("/train_model"):
            send_telegram_message(chat_id, _cmd_train())
            return {"ok": True}

        # Метрики
        if text.startswith("/metrics"):
            send_telegram_message(chat_id, _cmd_metrics_url())
            return {"ok": True}

        # Runtime-настройки
        if text.startswith("/settrade"):
            args = text.split()[1:]
            msg = _apply_runtime_updates("trade", args)
            send_telegram_message(chat_id, msg)
            return {"ok": True}

        if text.startswith("/setrisk"):
            args = text.split()[1:]
            msg = _apply_runtime_updates("risk", args)
            send_telegram_message(chat_id, msg)
            return {"ok": True}

        # Управление вебхуком
        if text.startswith("/setwebhook"):
            url = PUBLIC_URL + "/telegram/webhook" if PUBLIC_URL else None
            if len(text.split()) > 1:
                url = text.split()[1].strip()
            if not url:
                send_telegram_message(chat_id, "URL вебхука не указан и PUBLIC_URL отсутствует")
                return {"ok": True}
            payload = {"url": url}
            if TELEGRAM_SECRET_TOKEN:
                payload["secret_token"] = TELEGRAM_SECRET_TOKEN
            res = _post("setWebhook", payload)
            send_telegram_message(chat_id, f"setWebhook → {res}")
            return {"ok": True}

        if text.startswith("/getwebhook"):
            res = _post("getWebhookInfo", {})
            send_telegram_message(chat_id, f"{res}")
            return {"ok": True}

        if text.startswith("/delwebhook"):
            res = _post("deleteWebhook", {})
            send_telegram_message(chat_id, f"deleteWebhook → {res}")
            return {"ok": True}

        # Unknown
        send_telegram_message(chat_id, "Unknown. Try /config /alive /ping /version")
        return {"ok": True}

    except Exception as e:
        try:
            chat_id = update.get("message", {}).get("chat", {}).get("id")
            if chat_id:
                send_telegram_message(chat_id, f"Ошибка: {e}")
        except Exception:
            pass
        return {"ok": True}
