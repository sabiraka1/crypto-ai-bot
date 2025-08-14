# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Telegram interface for trading system (production-ready).
- Чёткие описания команд
- /status → ТЕКСТ (без графика)
- /chart  → График (Matplotlib Agg)
- /testbuy /testsell → тестовые сделки (через движок; фоллбэк — paper-эмуляция)
- Сервис: /setwebhook /getwebhook /delwebhook /metrics
- Runtime твики: /settrade /setrisk
- Ленивая загрузка pandas/matplotlib/ccxt → быстрый старт контейнера
"""

import os
import io
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

# ---- Hooks в систему (с фоллбэками)
try:
    from crypto_ai_bot.trading.bot import get_bot, Settings
except Exception:
    get_bot = None
    Settings = None

try:
    from crypto_ai_bot.analysis.technical_indicators import calculate_all_indicators
except Exception:
    calculate_all_indicators = None

try:
    from crypto_ai_bot.analysis.sinyal_skorlayici import train_model as _train_model
except Exception:
    _train_model = None


# ---- ENV (только для этого модуля; остальное — через Settings в движке)
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_IDS = [s.strip() for s in (os.getenv("ADMIN_CHAT_IDS") or "").split(",") if s.strip()]
PUBLIC_URL = os.getenv("PUBLIC_URL")
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN")

SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
TIMEFRAME = os.getenv("TIMEFRAME", "15m")

PAPER_ORDERS_FILE = os.getenv("PAPER_ORDERS_FILE", "paper_orders.csv")
PAPER_POSITIONS_FILE = os.getenv("PAPER_POSITIONS_FILE", "paper_positions.json")
PAPER_PNL_FILE = os.getenv("PAPER_PNL_FILE", "paper_pnl.csv")
SIGNALS_CSV = os.getenv("SIGNALS_CSV", "signals_snapshots.csv")


# ============================= Telegram helpers ============================= #

def _api_url(method: str) -> str:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

def _post(method: str, data: Dict[str, Any], files: Dict[str, Any] | None = None) -> Dict[str, Any]:
    try:
        r = requests.post(_api_url(method), data=data, files=files, timeout=10)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send_telegram_message(chat_id: int | str, text: str, *, html: bool = True) -> Dict[str, Any]:
    data = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if html:
        data["parse_mode"] = "HTML"
    return _post("sendMessage", data)

def send_telegram_photo(chat_id: int | str, image_bytes: bytes, caption: Optional[str] = None) -> Dict[str, Any]:
    return _post("sendPhoto", {"chat_id": chat_id, "caption": caption or ""}, files={"photo": ("chart.png", image_bytes)})


# ================================ Lazy imports ============================== #

def _lazy_pd():
    import pandas as pd  # noqa
    return pd

def _lazy_ccxt():
    import ccxt  # noqa
    return ccxt

def _lazy_mpl():
    import matplotlib  # noqa
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa
    return plt


# ================================ I/O helpers =============================== #

def _load_df_csv(path: str, n_tail: int = 25):
    if not os.path.exists(path):
        return None
    try:
        pd = _lazy_pd()
        df = pd.read_csv(path, on_bad_lines="skip")
        return df.tail(n_tail) if n_tail else df
    except Exception:
        return None

def _read_positions() -> Dict[str, Any]:
    if not os.path.exists(PAPER_POSITIONS_FILE):
        return {}
    try:
        with open(PAPER_POSITIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _read_positions_short() -> str:
    pos = _read_positions()
    if not pos:
        return "Позиций нет"
    return f"Позиция: {pos.get('side','-')} {pos.get('amount',0)} @ {pos.get('entry_price',0)}"

def _write_positions(obj: Dict[str, Any]) -> None:
    try:
        with open(PAPER_POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:
        pass

def _append_csv(path: str, row: Dict[str, Any]) -> None:
    try:
        pd = _lazy_pd()
        import os as _os
        if _os.path.exists(path):
            df = pd.read_csv(path, on_bad_lines="skip")
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row])
        df.to_csv(path, index=False)
    except Exception:
        pass


# =============================== Exchange / OHLCV =========================== #

def _get_exchange():
    # 1) реюзим exchange у движка (единые лимиты/настройки)
    if get_bot is not None:
        try:
            b = get_bot()
            if b and getattr(b, "exchange", None):
                return b.exchange
        except Exception:
            pass
    # 2) прямой ccxt.gateio (env)
    try:
        ccxt = _lazy_ccxt()
        key = os.getenv("GATE_API_KEY") or os.getenv("API_KEY")
        sec = os.getenv("GATE_API_SECRET") or os.getenv("API_SECRET")
        return ccxt.gateio({"apiKey": key, "secret": sec, "enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "spot"}})
    except Exception:
        return None

def _fetch_ohlcv(symbol: str, timeframe: str, limit: int = 200):
    ex = _get_exchange()
    if ex is None:
        return None
    try:
        data = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        pd = _lazy_pd()
        df = pd.DataFrame(data, columns=["time","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df.set_index("time", inplace=True)
        return df
    except Exception:
        return None

def _fetch_price(symbol: str) -> Optional[float]:
    ex = _get_exchange()
    if ex is None:
        return None
    try:
        t = ex.fetch_ticker(symbol)
        return float(t["last"])
    except Exception:
        return None


# ================================= Charts ================================== #

def _plot_ohlcv_with_indicators(df) -> bytes:
    if df is None or df.empty:
        raise RuntimeError("Нет данных для графика")
    plt = _lazy_mpl()
    feats = df.copy()
    if calculate_all_indicators is not None:
        try:
            feats = calculate_all_indicators(df).dropna()
        except Exception:
            pass

    fig, ax = plt.subplots(figsize=(10, 5), dpi=140)
    ax.plot(feats.index, feats["close"], label="Close")
    if "ema20" in feats.columns: ax.plot(feats.index, feats["ema20"], label="EMA20")
    if "ema50" in feats.columns: ax.plot(feats.index, feats["ema50"], label="EMA50")
    ax.set_title("OHLCV + EMA(20/50)")
    ax.grid(True, alpha=0.3)
    ax.legend()

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ================================= Commands ================================= #

def _cmd_help() -> str:
    return (
        "<b>Справка по командам</b>\n"
        "— <b>/start</b> — приветствие\n"
        "— <b>/help</b> — эта справка\n"
        "— <b>/config</b> — текущие настройки (Settings)\n"
        "— <b>/status</b> — цена, ATR%, позиция (текст)\n"
        "— <b>/chart</b> [SYMBOL] [TF] — график OHLCV+EMA\n"
        "— <b>/test</b> [SYMBOL] [TF] — быстрая сводка (без графика)\n"
        "— <b>/profit</b>, <b>/profit_chart</b> — итоговый PnL и его график (paper)\n"
        "— <b>/orders</b>, <b>/positions</b>, <b>/close</b> — ордера/позиции/закрытие\n"
        "— <b>/testbuy</b> &lt;amt&gt;, <b>/testsell</b> &lt;amt&gt; — тестовые сделки\n"
        "— <b>/train</b> — обучение модели (если модуль доступен)\n"
        "— <b>/errors</b> — хвост логов/сигналов\n"
        "— <b>/settrade</b> k=v …, <b>/setrisk</b> k=v … — твики на лету (до рестарта)\n"
        "— <b>/setwebhook</b> / <b>/getwebhook</b> / <b>/delwebhook</b> — управление вебхуком\n"
        "— <b>/metrics</b>, <b>/ping</b>, <b>/version</b>\n"
        "\nПримеры:\n"
        "• /chart BTC/USDT 15m\n"
        "• /test BTC/USDT 1h\n"
        "• /testbuy 10\n"
    )

def _build_cfg_string(cfg) -> str:
    try:
        fields = [
            ("SYMBOL", cfg.SYMBOL), ("TIMEFRAME", cfg.TIMEFRAME), ("TRADE_AMOUNT", cfg.TRADE_AMOUNT),
            ("ENABLE_TRADING", cfg.ENABLE_TRADING), ("SAFE_MODE", cfg.SAFE_MODE), ("PAPER_MODE", cfg.PAPER_MODE),
            ("AI_MIN_TO_TRADE", getattr(cfg, "AI_MIN_TO_TRADE", None)),
            ("MIN_SCORE_TO_BUY", getattr(cfg, "MIN_SCORE_TO_BUY", None)),
            ("USE_CONTEXT_PENALTIES", getattr(cfg, "USE_CONTEXT_PENALTIES", None)),
            ("CTX_CLAMP", f"[{getattr(cfg,'CTX_SCORE_CLAMP_MIN',0.0)},{getattr(cfg,'CTX_SCORE_CLAMP_MAX',1.0)}]"),
        ]
        return "<b>Config (Settings)</b>\n" + " ".join(f"{k}={v}" for k,v in fields if v is not None)
    except Exception:
        return "Config: недоступно (ошибка Settings)"

def _cmd_status() -> str:
    sym, tf = SYMBOL, TIMEFRAME
    price = _fetch_price(sym)
    atrp = None
    try:
        df = _fetch_ohlcv(sym, tf, limit=120)
        if df is not None and not df.empty and calculate_all_indicators is not None:
            feats = calculate_all_indicators(df).dropna()
            if not feats.empty:
                atrp = (feats["atr"].iloc[-1] / feats["close"].iloc[-1]) * 100.0
    except Exception:
        pass
    parts = []
    if price is not None:
        parts.append(f"ℹ️ {sym} @ {price:,.2f}")
    if atrp is not None:
        parts.append(f"ATR%≈{atrp:.2f}")
    parts.append(_read_positions_short())
    return " | ".join(parts)

def _cmd_profit() -> str:
    df = _load_df_csv(PAPER_PNL_FILE, n_tail=0)
    if df is None or df.empty:
        return "PnL: пока нет данных"
    try:
        pnl = float(df["pnl_usd"].sum())
        n = len(df)
        return f"PnL (paper): {pnl:+.2f} USD, закрытых сделок: {n}"
    except Exception:
        return "PnL: ошибка чтения"

def _cmd_profit_chart() -> Optional[bytes]:
    df = _load_df_csv(PAPER_PNL_FILE, n_tail=0)
    if df is None or df.empty:
        return None
    plt = _lazy_mpl()
    try:
        equity = df["pnl_usd"].cumsum()
        fig, ax = plt.subplots(figsize=(10, 5), dpi=140)
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
        return "Ордеров пока нет"
    cols = [c for c in df.columns][:8]
    return "Последние ордера:\n" + df[cols].to_string(index=False)

def _cmd_positions() -> str:
    return _read_positions_short()

def _cmd_close() -> str:
    # через движок, если умеет
    if get_bot is not None:
        try:
            bot = get_bot()
            if bot and hasattr(bot, "request_close_position"):
                ok = bot.request_close_position()
                if ok is False:
                    return "Не удалось отправить запрос на закрытие"
                return "Запрос на закрытие отправлен"
        except Exception:
            pass
    # фоллбэк: ручная фиксация PnL в paper
    pos = _read_positions()
    if not pos:
        return "Позиции нет"
    price = _fetch_price(SYMBOL)
    if price is None:
        return "Не удалось получить цену"
    side, amt, entry = pos.get("side"), float(pos.get("amount", 0)), float(pos.get("entry_price", 0))
    pnl = (price - entry) * amt * (1 if side == "buy" else -1)
    ts = int(time.time())
    _append_csv(PAPER_ORDERS_FILE, {"ts": ts, "symbol": SYMBOL, "side": "sell" if side=="buy" else "buy",
                                    "amount": amt, "price": price, "note": "manual close"})
    _append_csv(PAPER_PNL_FILE, {"ts": ts, "symbol": SYMBOL, "pnl_usd": pnl})
    _write_positions({})
    return f"Закрыто @ {price:.2f}, PnL={pnl:+.2f} USD"

def _cmd_chart(args: List[str]) -> Tuple[Optional[bytes], str]:
    sym, tf = SYMBOL, TIMEFRAME
    if args:
        if len(args) >= 1: sym = args[0].upper().replace(":", "/")
        if len(args) >= 2: tf = args[1]
    df = _fetch_ohlcv(sym, tf, limit=200)
    if df is None or df.empty:
        return None, "Нет данных для графика"
    try:
        img = _plot_ohlcv_with_indicators(df)
        return img, f"{sym} {tf}"
    except Exception as e:
        return None, f"Ошибка графика: {e}"

def _cmd_test(args: List[str]) -> str:
    sym, tf = SYMBOL, TIMEFRAME
    if args:
        if len(args) >= 1: sym = args[0].upper().replace(":", "/")
        if len(args) >= 2: tf = args[1]
    df = _fetch_ohlcv(sym, tf, limit=120)
    if df is None or df.empty:
        return "Нет данных"
    ai = os.getenv("AI_MIN_TO_TRADE", "0.55")
    rule = os.getenv("MIN_SCORE_TO_BUY", "0.65")
    atrp, last_close = None, float(df["close"].iloc[-1])
    try:
        if calculate_all_indicators is not None:
            feats = calculate_all_indicators(df).dropna()
            if not feats.empty:
                atrp = (feats["atr"].iloc[-1] / feats["close"].iloc[-1]) * 100.0
    except Exception:
        pass
    parts = [f"ℹ️ {sym} @ {last_close:,.2f}", f"rule={rule}", f"ai={ai}"]
    if atrp is not None:
        parts.append(f"ATR%≈{atrp:.2f}")
    return " | ".join(parts)

def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None

def _cmd_test_order(side: str, amt_s: str) -> str:
    amt = _parse_float(amt_s)
    if not amt or amt <= 0:
        return "Неверная сумма"
    # через движок (предпочтительно)
    if get_bot is not None:
        try:
            bot = get_bot()
            if bot and hasattr(bot, "request_market_order"):
                ok = bot.request_market_order(side, amt)
                if ok is False:
                    return "Не удалось отправить ордер через движок"
                return f"Тестовый ордер через движок: {side} {amt}"
        except Exception:
            pass
    # фоллбэк: paper-эмуляция
    price = _fetch_price(SYMBOL)
    if price is None:
        return "Не удалось получить цену"
    ts = int(time.time())
    _append_csv(PAPER_ORDERS_FILE, {"ts": ts, "symbol": SYMBOL, "side": side, "amount": amt, "price": price, "note": "test"})
    if side == "buy":
        _write_positions({"side": "buy", "amount": amt, "entry_price": price, "ts": ts})
    else:
        # sell: если есть лонг — закрываем с записью PnL
        pos = _read_positions()
        if pos and pos.get("side") == "buy":
            entry = float(pos.get("entry_price", 0))
            pnl = (price - entry) * float(pos.get("amount", 0))
            _append_csv(PAPER_PNL_FILE, {"ts": ts, "symbol": SYMBOL, "pnl_usd": pnl})
            _write_positions({})
    return f"Тестовый {side} {amt} @ {price:.2f}"

def _cmd_metrics() -> str:
    return f"{PUBLIC_URL}/metrics" if PUBLIC_URL else "Metrics URL не задан"


# ============================= Webhook dispatcher ============================ #

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
            send_telegram_message(chat_id, "Привет! Наберите /help, чтобы увидеть список команд.")
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
                send_telegram_message(chat_id, _build_cfg_string(cfg))
            return {"ok": True}

        # Статус/отчёты
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
        if text.startswith("/train"):
            msg = _train_model() if _train_model else "Модуль обучения недоступен"
            send_telegram_message(chat_id, msg)
            return {"ok": True}

        # Тестовые сделки
        if text.startswith("/testbuy"):
            parts = text.split()
            send_telegram_message(chat_id, _cmd_test_order("buy", parts[1] if len(parts) > 1 else ""))
            return {"ok": True}

        if text.startswith("/testsell"):
            parts = text.split()
            send_telegram_message(chat_id, _cmd_test_order("sell", parts[1] if len(parts) > 1 else ""))
            return {"ok": True}

        # Runtime настройки
        if text.startswith("/settrade") or text.startswith("/setrisk"):
            kind = "trade" if text.startswith("/settrade") else "risk"
            args = text.split()[1:]
            if get_bot is None or Settings is None:
                send_telegram_message(chat_id, "Settings недоступен")
                return {"ok": True}
            bot = get_bot()
            if not bot or not getattr(bot, "settings", None):
                send_telegram_message(chat_id, "Config недоступен")
                return {"ok": True}
            cfg = bot.settings
            changed = []
            for pair in args:
                if "=" not in pair: continue
                k, v = pair.split("=", 1)
                k = k.strip().upper(); v = v.strip()
                parsed: Any = v
                if v.lower() in ("1","true","yes","on"): parsed = 1
                elif v.lower() in ("0","false","no","off"): parsed = 0
                else:
                    try:
                        parsed = float(v) if "." in v else int(v)
                    except Exception:
                        pass
                if hasattr(cfg, k):
                    try:
                        setattr(cfg, k, parsed); changed.append(f"{k}={parsed}")
                    except Exception:
                        pass
            send_telegram_message(chat_id, "Обновлено (до рестарта): " + (", ".join(changed) if changed else "ничего"))
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

        if text.startswith("/metrics"):
            send_telegram_message(chat_id, _cmd_metrics())
            return {"ok": True}

        # Unknown
        send_telegram_message(chat_id, "Неизвестная команда. Попробуйте /help")
        return {"ok": True}

    except Exception as e:
        try:
            chat_id = update.get("message", {}).get("chat", {}).get("id")
            if chat_id:
                send_telegram_message(chat_id, f"Ошибка: {e}")
        except Exception:
            pass
        return {"ok": True}
