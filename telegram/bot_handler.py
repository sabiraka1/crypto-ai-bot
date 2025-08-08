import os
import logging
import requests
import pandas as pd
from typing import Optional, Callable, List
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analysis import scoring_engine
from trading.exchange_client import ExchangeClient

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None


def _tg_request(method: str, data: dict, files: Optional[dict] = None) -> None:
    if not TELEGRAM_API or not CHAT_ID:
        logging.warning("Telegram not configured")
        return
    url = f"{TELEGRAM_API}/{method}"
    try:
        resp = requests.post(url, data=data, files=files, timeout=15)
        if resp.status_code != 200:
            logging.error("Telegram API error: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logging.exception("Telegram request failed: %s", e)


def send_message(text: str) -> None:
    _tg_request("sendMessage", {"chat_id": CHAT_ID, "text": text})


def send_photo(image_path: str, caption: Optional[str] = None) -> None:
    if not os.path.exists(image_path):
        logging.warning("send_photo: file not found: %s", image_path)
        return
    with open(image_path, "rb") as f:
        files = {"photo": f}
        data = {"chat_id": CHAT_ID}
        if caption:
            data["caption"] = caption
        _tg_request("sendPhoto", data, files=files)


def cmd_start() -> None:
    send_message(
        "🚀 Торговый бот запущен!\n\n"
        "/status – позиция\n"
        "/profit – PnL\n"
        "/errors – ошибки\n"
        "/lasttrades – последние сделки\n"
        "/train – обучение\n"
        "/test – тест-сигнал"
    )


def cmd_status(state_manager, price_getter: Callable[[], Optional[float]]) -> None:
    st = getattr(state_manager, "state", {}) or {}
    if not st.get("in_position"):
        send_message("🟢 Позиции нет")
        return
    sym = st.get("symbol", "BTC/USDT")
    entry = float(st.get("entry_price") or 0.0)
    last = None
    try:
        last = price_getter()
        if last is not None:
            last = float(last)
    except Exception:
        pass
    txt = [f"📌 Позиция LONG {sym} @ {entry:.4f}"]
    if last:
        pnl_pct = (last - entry) / entry * 100.0 if entry else 0.0
        txt.append(f"Текущая цена: {last:.4f} | PnL {pnl_pct:.2f}%")
    tp = st.get("tp_price_pct"); sl = st.get("sl_price_pct")
    if tp and sl:
        txt.append(f"TP≈{tp:.4f} | SL≈{sl:.4f}")
    send_message("\n".join(txt))


def cmd_profit() -> None:
    path = "closed_trades.csv"
    if not os.path.exists(path):
        send_message("📊 PnL: 0.00\nWinrate: 0.0%")
        return
    try:
        df = pd.read_csv(path)
        pnl = float(df.get("pnl_abs", pd.Series([0.0])).sum())
        wins = int((df.get("pnl_pct", pd.Series([])) > 0).sum())
        total = int(len(df))
        wr = (wins / total * 100.0) if total else 0.0
        send_message(f"📊 PnL: {pnl:.2f}\nWinrate: {wr:.1f}%\nТрейдов: {total}")
    except Exception as e:
        logging.error("cmd_profit error: %s", e)
        send_message(f"⚠️ Ошибка: {e}")


def notify_entry(symbol: str, price: float, amount_usd: float, tp: float, sl: float, tp1: float, tp2: float,
                 buy_score: float = None, ai_score: float = None, amount_frac: float = None):
    expl = []
    if buy_score is not None and ai_score is not None:
        expl.append(f"Buy {buy_score:.2f} / AI {ai_score:.2f}")
    if amount_frac is not None:
        expl.append(f"Size {int(amount_frac*100)}%")
    send_message(
        f"📥 Вход LONG {symbol} @ {price}\n" +
        (" | ".join(expl) if expl else "") +
        f"\nСумма: ${amount_usd}\nTP%: {tp:.2f} | SL%: {sl:.2f}\nTP1: {tp1:.2f} | TP2: {tp2:.2f}"
    )


def notify_close(symbol: str, price: float, reason: str, pnl_pct: float, pnl_abs: float = None,
                 buy_score: float = None, ai_score: float = None, amount_usd: float = None):
    extra = []
    if buy_score is not None and ai_score is not None:
        extra.append(f"Buy {buy_score:.2f} / AI {ai_score:.2f}")
    if amount_usd is not None:
        extra.append(f"Size ${amount_usd:.2f}")
    base = f"📤 Закрытие {symbol} @ {price}\n{reason} | PnL {pnl_pct:.2f}%" + ("\n" + " | ".join(extra) if extra else "")
    if pnl_abs is not None:
        base += f" ({pnl_abs:.2f}$)"
    send_message(base)
