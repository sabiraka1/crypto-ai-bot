
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
crypto_ai_bot/telegram/bot.py
-----------------------------
Telegram-бот (вебхук) с широким набором команд.
Добавлено: /config теперь показывает значения из Settings (если доступен).
"""

import os
import io
import csv
import json
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Tuple

import requests

# Matplotlib: headless backend для Railway/Replit
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

# Попытаться подтянуть Settings для красивого /config
try:
    from crypto_ai_bot.trading.bot import Settings as _Settings
except Exception:
    _Settings = None

# ------------ ENV ------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_IDS = os.getenv("ADMIN_CHAT_IDS") or os.getenv("CHAT_ID") or ""
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
TIMEFRAME = os.getenv("TIMEFRAME", "15m")
TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", "10"))
SAFE_MODE = int(os.getenv("SAFE_MODE", "1"))
PAPER_MODE = int(os.getenv("PAPER_MODE", "1"))

PAPER_POSITIONS_FILE = os.getenv("PAPER_POSITIONS_FILE", "paper_positions.json")
PAPER_ORDERS_FILE    = os.getenv("PAPER_ORDERS_FILE", "paper_orders.csv")
PAPER_PNL_FILE       = os.getenv("PAPER_PNL_FILE", "paper_pnl.csv")

CLOSED_TRADES_CSV = os.getenv("CLOSED_TRADES_CSV", "closed_trades.csv")
SIGNALS_CSV       = os.getenv("SIGNALS_CSV", "sinyal_fiyat_analizi.csv")

GATE_API_KEY    = os.getenv("GATE_API_KEY") or os.getenv("API_KEY")
GATE_API_SECRET = os.getenv("GATE_API_SECRET") or os.getenv("API_SECRET")

APP_VERSION = os.getenv("APP_VERSION", "1.0.0")


# ------------ Telegram helpers ------------
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
    if not chat_ids:
        return
    for cid in chat_ids:
        _tg_request("sendMessage", {"chat_id": cid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})

def send_telegram_photo(caption: str, fig) -> None:
    chat_ids = [c.strip() for c in ADMIN_CHAT_IDS.split(",") if c.strip()]
    if not chat_ids:
        return
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    for cid in chat_ids:
        files = {"photo": ("chart.png", buf, "image/png")}
        _tg_request("sendPhoto", {"chat_id": cid, "caption": caption}, files=files)
    buf.close()


# ------------ Market helpers ------------
def _exchange() -> Any:
    if not ccxt:
        return None
    return ccxt.gateio({
        "apiKey": GATE_API_KEY,
        "secret": GATE_API_SECRET,
        "enableRateLimit": True,
        "timeout": 20000,
        "options": {"defaultType": "spot"}
    })

def _fetch_ohlcv(symbol: str, timeframe: str, limit: int = 200) -> List[List[float]]:
    ex = _exchange()
    if not ex:
        return []
    return ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

def _last_price(symbol: str) -> float:
    ex = _exchange()
    if not ex:
        return 0.0
    try:
        t = ex.fetch_ticker(symbol)
        return float(t.get("last") or t.get("close") or 0.0)
    except Exception:
        return 0.0


# ------------ CSV helpers ------------
def _safe_read_csv(path: str) -> Optional["pd.DataFrame"]:
    if not pd or not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path, engine="python", on_bad_lines="skip")
    except Exception:
        try:
            return pd.read_csv(path, engine="python", on_bad_lines="skip", sep=";")
        except Exception:
            return None

def _paper_positions() -> List[Dict[str, Any]]:
    if not os.path.exists(PAPER_POSITIONS_FILE):
        return []
    try:
        with open(PAPER_POSITIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("open", [])
    except Exception:
        return []


# ------------ Commands ------------
def cmd_start(chat_id: str):
    send_telegram_message(
        "<b>Привет! Я готов 🤖</b>\n"
        "Команды: /help — все, /status, /profit, /profit_chart, /errors, /orders, /positions, /close, "
        "/chart, /test, /train, /train_model, /signal, /signals, /metrics, /config, /settrade, /setrisk, "
        "/balance, /history, /version, /webhook, /log", chat_id
    )

def cmd_help(chat_id: str):
    send_telegram_message(
        "<b>Команды</b>\n"
        "/status — состояние позиции, цена, PnL\n"
        "/profit — суммарная прибыль/убыток\n"
        "/profit_chart — график прибыли\n"
        "/errors — последние строки из CSV сигналов\n"
        "/orders — последние заявки (paper)\n"
        "/positions — открытые позиции (paper)\n"
        "/close — закрыть текущую позицию (paper)\n"
        "/chart — свежий график цены\n"
        "/test — тестовый сигнал/график\n"
        "/train, /train_model — обучение модели\n"
        "/signal, /signals — текущие оценки\n"
        "/metrics — метрики\n"
        "/config — важные настройки\n"
        "/settrade 25 — TRADE_AMOUNT=25\n"
        "/setrisk 2 1.5 — SL=2% TP=1.5%\n"
        "/balance — paper Δ\n"
        "/history — история сделок\n"
        "/version — версия\n"
        "/webhook — проверка вебхука\n"
        "/log — диагностический лог", chat_id
    )

def cmd_ping(chat_id: str): send_telegram_message("pong", chat_id)
def cmd_alive(chat_id: str): send_telegram_message("alive: ✅", chat_id)
def cmd_version(chat_id: str): send_telegram_message(f"version: {APP_VERSION}", chat_id)

def cmd_status(chat_id: str):
    pos = _paper_positions()
    price = _last_price(SYMBOL)
    if pos:
        p = pos[-1]
        side = p.get("side"); qty = float(p.get("qty", 0.0))
        entry = float(p.get("entry_price", 0.0))
        pnl_abs = (price - entry) * qty if side == "buy" else (entry - price) * qty
        pnl_pct = (price / entry - 1.0) * (100 if side == "buy" else -100) if entry > 0 else 0.0
        send_telegram_message(
            f"<b>Status</b>\n{SYMBOL} {side} qty={qty:.8f}\nentry={entry:.2f} price={price:.2f}\n"
            f"PnL={pnl_abs:.4f} ({pnl_pct:.2f}%)", chat_id
        )
    else:
        send_telegram_message(f"No open positions for {SYMBOL}. Price={price:.2f}", chat_id)

def cmd_profit(chat_id: str):
    df = _safe_read_csv(CLOSED_TRADES_CSV) or _safe_read_csv(PAPER_PNL_FILE)
    if df is None or df.empty:
        send_telegram_message("Нет данных о закрытых сделках.", chat_id); return
    try:
        total = float(df["pnl_abs"].sum()) if "pnl_abs" in df.columns else float(df.iloc[:, -1].astype(float).sum())
        send_telegram_message(f"Суммарная прибыль: {total:.4f} USDT", chat_id)
    except Exception as e:
        send_telegram_message(f"Ошибка чтения профита: {e}", chat_id)

def cmd_profit_chart(chat_id: str):
    df = _safe_read_csv(CLOSED_TRADES_CSV) or _safe_read_csv(PAPER_PNL_FILE)
    if df is None or df.empty:
        send_telegram_message("Нет данных для графика прибыли.", chat_id); return
    try:
        pnl = (df["pnl_abs"].astype(float).cumsum()
               if "pnl_abs" in df.columns else df.iloc[:, -1].astype(float).cumsum())
        fig = plt.figure()
        plt.plot(range(len(pnl)), pnl.values)
        plt.title("Cumulative PnL"); plt.xlabel("Trade #"); plt.ylabel("PnL (USDT)")
        send_telegram_photo("Cumulative PnL", fig)
    except Exception as e:
        send_telegram_message(f"График не построен: {e}", chat_id)

def cmd_errors(chat_id: str, limit: int = 15):
    df = _safe_read_csv(SIGNALS_CSV)
    if df is None or df.empty:
        send_telegram_message("Файл сигналов пуст или не найден.", chat_id); return
    try:
        tail = df.tail(limit)
        lines = []
        for _, row in tail.iterrows():
            try:
                ts = row.get("timestamp") or row.get("ts") or ""
                signal = row.get("signal") or row.get("decision") or ""
                price = row.get("price") or row.get("entry_price") or ""
                score = row.get("score") or row.get("ai_score") or row.get("rule_score") or ""
                lines.append(f"{ts} | {signal} | {price} | {score}")
            except Exception: pass
        send_telegram_message("<b>Последние сигналы</b>\n" + ("\n".join(lines) if lines else "—"), chat_id)
    except Exception as e:
        send_telegram_message(f"Ошибка чтения CSV: {e}", chat_id)

def cmd_orders(chat_id: str, limit: int = 20):
    if not os.path.exists(PAPER_ORDERS_FILE):
        send_telegram_message("Файл заявок не найден.", chat_id); return
    try:
        rows = []
        with open(PAPER_ORDERS_FILE, "r", encoding="utf-8") as f:
            r = csv.reader(f); next(r, None)
            for row in r: rows.append(row)
        rows = rows[-limit:]
        send_telegram_message("<b>Последние заявки (paper)</b>\n" + "\n".join([" | ".join(x) for x in rows]), chat_id)
    except Exception as e:
        send_telegram_message(f"Ошибка чтения заявок: {e}", chat_id)

def cmd_positions(chat_id: str):
    pos = _paper_positions()
    if not pos: send_telegram_message("Открытых позиций нет.", chat_id); return
    lines = [f"{p.get('symbol')} {p.get('side')} qty={p.get('qty')} @ {p.get('entry_price')}" for p in pos]
    send_telegram_message("<b>Открытые позиции</b>\n" + "\n".join(lines), chat_id)

def cmd_close(chat_id: str):
    pos = _paper_positions()
    if not pos: send_telegram_message("Позиции нет.", chat_id); return
    p = pos[-1]; price = _last_price(SYMBOL)
    qty = float(p.get("qty", 0.0)); entry = float(p.get("entry_price", 0.0))
    side = "sell" if p.get("side") == "buy" else "buy"
    pnl_abs = (price - entry) * qty if side == "sell" else (entry - price) * qty
    pnl_pct = (price / entry - 1.0) * (100 if side == "sell" else -100) if entry > 0 else 0.0
    try:
        with open(PAPER_PNL_FILE, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([p.get("opened_at"), datetime.now(timezone.utc).isoformat(), SYMBOL, p.get("side"), qty, entry, price, pnl_abs, pnl_pct])
        with open(PAPER_POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump({"open": []}, f)
        send_telegram_message(f"Позиция закрыта @ {price:.2f} | PnL={pnl_abs:.4f} ({pnl_pct:.2f}%)", chat_id)
    except Exception as e:
        send_telegram_message(f"Не удалось закрыть позицию: {e}", chat_id)

def cmd_chart(chat_id: str, limit: int = 150):
    try:
        ohlcv = _fetch_ohlcv(SYMBOL, TIMEFRAME, limit=limit)
        if not ohlcv: send_telegram_message("Нет данных OHLCV.", chat_id); return
        xs = list(range(len(ohlcv))); closes = [c[4] for c in ohlcv]
        fig = plt.figure(); plt.plot(xs, closes)
        plt.title(f"{SYMBOL} ({TIMEFRAME})"); plt.xlabel("Bar #"); plt.ylabel("Close")
        send_telegram_photo(f"{SYMBOL} ({TIMEFRAME})", fig)
    except Exception as e:
        send_telegram_message(f"Ошибка построения графика: {e}", chat_id)

def cmd_test(chat_id: str):
    price = _last_price(SYMBOL)
    send_telegram_message(f"Тестовый сигнал: {SYMBOL} @ {price:.2f} | TRADE_AMOUNT={TRADE_AMOUNT}", chat_id)
    cmd_chart(chat_id, limit=100)

def cmd_train(chat_id: str):
    try:
        try:
            from crypto_ai_bot.analysis.sinyal_skorlayici import train_model  # приоритетно
        except Exception:
            from crypto_ai_bot.sinyal_skorlayici import train_model          # fallback
        result = train_model()
        send_telegram_message(f"Обучение завершено: {result}", chat_id)
    except Exception as e:
        send_telegram_message(f"Не удалось запустить обучение: {e}", chat_id)

def cmd_train_model(chat_id: str): cmd_train(chat_id)
def cmd_signal(chat_id: str):
    price = _last_price(SYMBOL)
    send_telegram_message(f"Сигнал: цена {SYMBOL}={price:.2f} — детали в /signals", chat_id)
def cmd_signals(chat_id: str):
    price = _last_price(SYMBOL)
    send_telegram_message(f"<b>Signals</b>\nprice={price:.2f}\n(rule/ai показываются ботом в статусах)", chat_id)

def cmd_metrics(chat_id: str):
    # Текстовый снэпшот. Для Prometheus есть эндпоинт на сервере.
    send_telegram_message("metrics: см. /metrics на сервере (Prometheus format)", chat_id)

def _fmt_bool(v: int) -> str:
    return "on ✅" if int(v) == 1 else "off ⛔"

def cmd_config(chat_id: str):
    if _Settings is not None:
        cfg = _Settings.build()
        text = (
            "<b>Config (Settings)</b>\n"
            f"SYMBOL={cfg.SYMBOL}  TIMEFRAME={cfg.TIMEFRAME}\n"
            f"TRADE_AMOUNT={cfg.TRADE_AMOUNT}  ENABLE_TRADING={cfg.ENABLE_TRADING}\n"
            f"SAFE_MODE={cfg.SAFE_MODE} ({_fmt_bool(cfg.SAFE_MODE)})  PAPER_MODE={cfg.PAPER_MODE} ({_fmt_bool(cfg.PAPER_MODE)})\n"
            f"AI_MIN_TO_TRADE={cfg.AI_MIN_TO_TRADE}  MIN_SCORE_TO_BUY={cfg.MIN_SCORE_TO_BUY}\n"
            f"USE_CONTEXT_PENALTIES={cfg.USE_CONTEXT_PENALTIES}\n"
            f"CTX_BTC_DOM_THRESH={getattr(cfg,'CTX_BTC_DOM_THRESH', '—')}  CTX_DXY_DELTA_THRESH={getattr(cfg,'CTX_DXY_DELTA_THRESH','—')}\n"
            f"CTX_FNG_OVERHEATED={getattr(cfg,'CTX_FNG_OVERHEATED','—')}  CTX_FNG_UNDERSHOOT={getattr(cfg,'CTX_FNG_UNDERSHOOT','—')}\n"
        )
    else:
        # Fallback: показать ENV
        text = (
            "<b>Config (ENV)</b>\n"
            f"SYMBOL={SYMBOL}  TIMEFRAME={TIMEFRAME}\n"
            f"TRADE_AMOUNT={TRADE_AMOUNT}\n"
            f"SAFE_MODE={SAFE_MODE}  PAPER_MODE={PAPER_MODE}\n"
        )
    send_telegram_message(text, chat_id)

def cmd_settrade(chat_id: str, amt: str):
    global TRADE_AMOUNT
    try:
        TRADE_AMOUNT = float(amt); send_telegram_message(f"TRADE_AMOUNT={TRADE_AMOUNT}", chat_id)
    except Exception:
        send_telegram_message("Использование: /settrade 10", chat_id)

def cmd_setrisk(chat_id: str, sl: str, tp: str):
    os.environ["STOP_LOSS_PCT"] = str(sl); os.environ["TAKE_PROFIT_PCT"] = str(tp)
    send_telegram_message(f"STOP_LOSS_PCT={sl} TAKE_PROFIT_PCT={tp}", chat_id)

def cmd_balance(chat_id: str):
    df = _safe_read_csv(PAPER_PNL_FILE)
    total = float(df["pnl_abs"].sum()) if df is not None and "pnl_abs" in df.columns else 0.0
    send_telegram_message(f"Paper balance Δ: {total:.4f} USDT", chat_id)

def cmd_history(chat_id: str, limit: int = 20):
    df = _safe_read_csv(PAPER_PNL_FILE) or _safe_read_csv(CLOSED_TRADES_CSV)
    if df is None or df.empty: send_telegram_message("История пуста.", chat_id); return
    last = df.tail(limit); lines = []
    for _, r in last.iterrows():
        try:
            lines.append(f"{r.iloc[0]} | {r.iloc[2]} | {float(r.iloc[-2]):.4f} ({float(r.iloc[-1]):.2f}%)")
        except Exception: pass
    send_telegram_message("<b>История</b>\n" + "\n".join(lines), chat_id)

def cmd_webhook(chat_id: str): send_telegram_message("Webhook OK", chat_id)
def cmd_log(chat_id: str): send_telegram_message("Log snapshot: (см. Railway logs)", chat_id)
def cmd_unknown(chat_id: str, text: str): send_telegram_message(f"Неизвестная команда: {text}\n/help — список.", chat_id)

# ------------ Dispatcher ------------
def _parse_command(text: str) -> Tuple[str, List[str]]:
    if not text: return "", []
    parts = text.strip().split(); cmd = parts[0].lower()
    if cmd.startswith("/"): cmd = cmd[1:]
    return cmd, parts[1:]

def _dispatch(chat_id: str, cmd: str, args: List[str]):
    try:
        if   cmd in ("start",): return cmd_start(chat_id)
        elif cmd in ("help",): return cmd_help(chat_id)
        elif cmd in ("ping",): return cmd_ping(chat_id)
        elif cmd in ("alive",): return cmd_alive(chat_id)
        elif cmd in ("version","v"): return cmd_version(chat_id)
        elif cmd in ("status",): return cmd_status(chat_id)
        elif cmd in ("profit",): return cmd_profit(chat_id)
        elif cmd in ("profit_chart","pnl","pnl_chart"): return cmd_profit_chart(chat_id)
        elif cmd in ("errors","err"): return cmd_errors(chat_id)
        elif cmd in ("orders",): return cmd_orders(chat_id)
        elif cmd in ("positions","open"): return cmd_positions(chat_id)
        elif cmd in ("close",): return cmd_close(chat_id)
        elif cmd in ("chart",): return cmd_chart(chat_id)
        elif cmd in ("test",): return cmd_test(chat_id)
        elif cmd in ("train",): return cmd_train(chat_id)
        elif cmd in ("train_model","retrain"): return cmd_train_model(chat_id)
        elif cmd in ("signal",): return cmd_signal(chat_id)
        elif cmd in ("signals",): return cmd_signals(chat_id)
        elif cmd in ("metrics",): return cmd_metrics(chat_id)
        elif cmd in ("config",): return cmd_config(chat_id)
        elif cmd in ("settrade",): return cmd_settrade(chat_id, args[0]) if args else send_telegram_message("Использование: /settrade 10", chat_id)
        elif cmd in ("setrisk",): return cmd_setrisk(chat_id, args[0], args[1]) if len(args)>=2 else send_telegram_message("Использование: /setrisk 2 1.5", chat_id)
        elif cmd in ("balance",): return cmd_balance(chat_id)
        elif cmd in ("history",): return cmd_history(chat_id)
        elif cmd in ("webhook",): return cmd_webhook(chat_id)
        elif cmd in ("log","logs"): return cmd_log(chat_id)
        else: return cmd_unknown(chat_id, "/" + cmd)
    except Exception as e:
        send_telegram_message(f"Ошибка /{cmd}: {e}", chat_id)

# ------------ Webhook entry ------------
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
