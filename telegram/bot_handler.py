import os
import logging
import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from typing import Optional, Callable, List

from analysis import scoring_engine
from trading.exchange_client import ExchangeClient

# ==== ENV ====
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

# ==== Telegram helpers ====
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

# ==== Notifications for trades ====
def notify_entry(symbol: str, side: str, price: float, amount: float, reason: str = "") -> None:
    msg = f"📈 Открыта {side.upper()} позиция\n" \
          f"Инструмент: {symbol}\n" \
          f"Цена входа: {price:.4f}\n" \
          f"Объём: {amount}\n"
    if reason:
        msg += f"Причина: {reason}"
    send_message(msg)

def notify_close(symbol: str, side: str, entry_price: float, exit_price: float, pnl_abs: float, pnl_pct: float, reason: str = "") -> None:
    emoji = "✅" if pnl_pct >= 0 else "❌"
    msg = f"{emoji} Закрыта {side.upper()} позиция\n" \
          f"{symbol}\n" \
          f"Вход: {entry_price:.4f} → Выход: {exit_price:.4f}\n" \
          f"PnL: {pnl_abs:.2f} USDT ({pnl_pct:.2f}%)\n"
    if reason:
        msg += f"Причина: {reason}"
    send_message(msg)

# ==== Commands ====
def cmd_start() -> None:
    send_message(
        "🚀 Торговый бот запущен!\n\n"
        "/status – Показать открытую позицию\n"
        "/profit – Общий PnL и Winrate\n"
        "/errors – Последние ошибки из лога\n"
        "/lasttrades – Последние сделки\n"
        "/train – Обучить модель\n"
        "/test – Тест сигнала\n"
        "/testbuy – Тестовая покупка\n"
        "/testsell – Тестовая продажа"
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
    tp = st.get("tp_price_pct")
    sl = st.get("sl_price_pct")
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

def cmd_errors() -> None:
    path = "bot_activity.log"
    if not os.path.exists(path):
        send_message("Лог-файл ещё не создан")
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-15:]
        send_message("Последние строки лога:\n" + "".join(lines))
    except Exception as e:
        send_message(f"⚠️ Ошибка чтения лога: {e}")

def cmd_lasttrades() -> None:
    path = "closed_trades.csv"
    if not os.path.exists(path):
        send_message("Сделок ещё нет")
        return
    try:
        df = pd.read_csv(path).tail(5)
        rows: List[str] = []
        for _, r in df.iterrows():
            side = str(r.get("side", "BUY"))
            e = float(r.get("entry_price", 0.0))
            x = float(r.get("exit_price", 0.0))
            reason = str(r.get("reason", ""))
            rows.append(f"- {side} {e:.1f}->{x:.1f} | {reason}")
        send_message("📋 Последние сделки:\n" + "\n".join(rows))
    except Exception as e:
        send_message(f"⚠️ Ошибка чтения сделок: {e}")

def cmd_train(train_func) -> None:
    send_message("🧠 Запуск обучения модели...")
    try:
        success = train_func()
        if success:
            send_message("✅ Модель успешно обучена!")
        else:
            send_message("❌ Ошибка при обучении модели")
    except Exception as e:
        logging.error(f"cmd_train error: {e}")
        send_message(f"❌ Ошибка обучения: {e}")

# ==== Test commands ====
def cmd_test(symbol: str = None, timeframe: str = None):
    symbol = symbol or os.getenv("SYMBOL", "BTC/USDT")
    timeframe = timeframe or os.getenv("TIMEFRAME", "15m")
    try:
        ex = ExchangeClient()
        ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=200)
        if not ohlcv:
            send_message(f"⚠️ Нет данных OHLCV для {symbol}")
            return
        df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df.set_index("time", inplace=True)

        # Исправлено: используем метод из scoring_engine, который реально существует
        engine = scoring_engine.ScoringEngine()
        scores = engine.calculate_scores(df) if hasattr(engine, "calculate_scores") else (0.0, 0.0, None)
        buy_score, ai_score, _ = scores

        last = ex.get_last_price(symbol)
        send_message(f"🧪 TEST {symbol}\nЦена: {last:.2f}\nBuy {buy_score:.2f} | AI {ai_score:.2f}")

        plt.figure(figsize=(10, 4))
        df["close"].plot()
        plt.title(f"TEST {symbol} — close")
        plt.tight_layout()
        plt.savefig("test_chart.png", dpi=120)
        plt.close()
        send_photo("test_chart.png")
    except Exception as e:
        logging.exception("cmd_test error")
        send_message(f"❌ TEST ошибка: {e}")

# ==== Router ====
def process_command(text: str, state_manager, exchange_client: ExchangeClient, train_func: Optional[Callable] = None):
    text = (text or "").strip()
    if not text.startswith("/"):
        return
    try:
        sym = os.getenv("SYMBOL", "BTC/USDT")
        if text.startswith("/start"):
            return cmd_start()
        if text.startswith("/status"):
            return cmd_status(state_manager, lambda: exchange_client.get_last_price(sym))
        if text.startswith("/profit"):
            return cmd_profit()
        if text.startswith("/errors"):
            return cmd_errors()
        if text.startswith("/lasttrades"):
            return cmd_lasttrades()
        if text.startswith("/train"):
            return cmd_train(train_func if train_func else (lambda: False))
        if text.startswith("/test"):
            return cmd_test()
        logging.info(f"Unknown or unsupported command: {text}")
        send_message(f"❓ Неизвестная команда: {text}")
    except Exception as e:
        logging.exception(f"process_command error: {e}")
        send_message(f"⚠️ Ошибка обработки команды: {e}")
