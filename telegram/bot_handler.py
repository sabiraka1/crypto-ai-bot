import os
import io
import logging
import requests
import pandas as pd
from datetime import datetime
from typing import Optional

# headless charts
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

TRADES_LOG_PATH = "trades.log"

def _post(method: str, **payload):
    try:
        r = requests.post(f"{API}/{method}", json=payload, timeout=20)
        r.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"Telegram API error: {e}")
        return False

def send_message(text: str, parse_mode: Optional[str] = None):
    data = {"chat_id": CHAT_ID, "text": text}
    if parse_mode:
        data["parse_mode"] = parse_mode
    _post("sendMessage", **data)

def send_photo_bytes(img: bytes, caption: str = ""):
    try:
        url = f"{API}/sendPhoto"
        files = {"photo": ("chart.png", img)}
        data = {"chat_id": CHAT_ID, "caption": caption}
        requests.post(url, data=data, files=files, timeout=30)
    except Exception as e:
        logging.error(f"Telegram photo error: {e}")

def send_chart(df: pd.DataFrame, entry: float = None, exit_: float = None, title: str = "Chart"):
    fig = plt.figure()
    plt.plot(df.index, df["close"])
    if entry is not None:
        plt.axhline(entry, linestyle="--")
    if exit_ is not None:
        plt.axhline(exit_, linestyle=":")
    plt.title(title)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    send_photo_bytes(buf.getvalue(), caption=title)

def explain_signal_short(rsi: float, adx: float, macd_hist: float, ema_fast_above: bool) -> str:
    parts = []
    parts.append("EMA↑" if ema_fast_above else "EMA↓")
    parts.append(f"RSI {int(rsi)}")
    parts.append("ADX strong" if adx >= 25 else "ADX weak")
    parts.append("MACD+" if macd_hist > 0 else "MACD-")
    return " / ".join(parts)

# -------------------- Команды --------------------
def cmd_start():
    send_message(
        "🤖 Crypto AI Bot\n"
        "/status – состояние позиции\n"
        "/profit – суммарный PnL\n"
        "/errors – последние ошибки\n"
        "/lasttrades – 5 последних сделок\n"
        "/train – переобучить модель\n"
        "/test – тест-сигнал"
    )

def cmd_status(state_manager, get_price_fn):
    st = state_manager.state
    if st.get("in_position"):
        last = None
        try:
            last = float(get_price_fn())
        except Exception:
            pass
        pnl = 0.0
        if last and st.get("entry_price"):
            pnl = (last - st["entry_price"]) / st["entry_price"] * 100
        send_message(
            f"📈 LONG открыта\n"
            f"Вход: {st.get('entry_price')} | TP: {st.get('tp')} | SL: {st.get('sl')}\n"
            f"Текущая: {last} | PnL: {pnl:.2f}%"
        )
    else:
        if os.path.exists(TRADES_LOG_PATH):
            try:
                with open(TRADES_LOG_PATH, "r", encoding="utf-8") as f:
                    lines = [l.strip() for l in f.readlines() if "BUY" in l.upper()]
                if lines:
                    send_message(f"🟢 Позиции нет\nПоследний вход: {lines[-1]}")
                    return
            except Exception as e:
                logging.error(f"Error reading trades.log: {e}")
        send_message("🟢 Позиции нет")

def cmd_profit(closed_csv_path="closed_trades.csv", open_log_path="trades.log"):
    """
    PnL по закрытым сделкам:
      - если есть qty_usd: pnl = (close - entry) * qty_usd / entry
      - иначе используем TRADE_AMOUNT из .env (по умолчанию 50)
    Плюс показываем последние ордера из trades.log.
    """
    TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", "50"))
    total_pnl = 0.0
    winrate = 0.0
    lines = []

    if os.path.exists(closed_csv_path):
        try:
            df = pd.read_csv(closed_csv_path)
            if not df.empty:
                if {"entry_price", "close_price"}.issubset(df.columns):
                    if "qty_usd" in df.columns:
                        pnl_series = (df["close_price"] - df["entry_price"]) * (df["qty_usd"] / df["entry_price"].replace(0, pd.NA))
                    else:
                        pnl_series = (df["close_price"] - df["entry_price"]) * (TRADE_AMOUNT / df["entry_price"].replace(0, pd.NA))
                    pnl_series = pnl_series.fillna(0)
                    total_pnl = float(pnl_series.sum())
                    winrate = float((pnl_series > 0).mean() * 100) if len(pnl_series) else 0.0
                elif "pnl_abs" in df.columns:
                    total_pnl = float(df["pnl_abs"].sum())
                    winrate = float((df["pnl_abs"] > 0).mean() * 100)
                else:
                    lines.append("⚠️ Формат closed_trades.csv неизвестен")
            else:
                lines.append("📭 Закрытых сделок нет")
        except Exception as e:
            logging.error(f"cmd_profit read csv error: {e}")
            lines.append("⚠️ Не удалось прочитать closed_trades.csv")
    else:
        lines.append("📭 Закрытых сделок нет")

    if os.path.exists(open_log_path):
        try:
            with open(open_log_path, "r", encoding="utf-8") as f:
                raw = [ln.strip() for ln in f.readlines() if ln.strip()]
            if raw:
                lines.append("\n📜 Последние ордера:")
                for row in raw[-5:]:
                    lines.append(row)
            else:
                lines.append("📜 Журнал ордеров пуст")
        except Exception as e:
            logging.error(f"cmd_profit read log error: {e}")
            lines.append("⚠️ Не удалось прочитать trades.log")
    else:
        lines.append("📂 trades.log ещё не создан")

    msg = f"💰 PnL: {total_pnl:.2f}\n📊 Winrate: {winrate:.1f}%"
    if lines:
        msg += "\n" + "\n".join(lines)
    send_message(msg)

def cmd_errors(csv_path="sinyal_fiyat_analizi.csv"):
    if not os.path.exists(csv_path):
        send_message("📂 Лог ошибок ещё не сформирован"); return
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        logging.error(f"cmd_errors read error: {e}")
        send_message("⚠️ Не удалось прочитать лог ошибок"); return
    if "result" not in df.columns:
        send_message("ℹ️ Лог ещё не размечен (нет колонки result)"); return

    bad = df[df["result"] == 0].tail(5)
    if bad.empty:
        send_message("✅ Ошибок не зафиксировано"); return

    lines = ["❌ Последние ошибки:"]
    for _, r in bad.iterrows():
        t = r.get("time", "")
        rsi = r.get("rsi", "")
        macd = r.get("macd", "")
        lines.append(f"- {t} | RSI {rsi} | MACD {macd}")
    send_message("\n".join(lines))

def cmd_lasttrades(closed_csv_path="closed_trades.csv"):
    if not os.path.exists(closed_csv_path):
        send_message("📭 Сделок ещё нет"); return
    df = pd.read_csv(closed_csv_path).tail(5)
    if df.empty:
        send_message("📭 Сделок ещё нет"); return
    lines = ["🧾 Последние сделки:"]
    for _, r in df.iterrows():
        t = r.get("time", r.get("close_time", ""))
        side = r.get("side", "LONG")
        ep = r.get("entry_price", "")
        cp = r.get("close_price", "")
        reason = r.get("reason", r.get("close_reason", ""))
        lines.append(f"- {t} | {side} {ep}→{cp} | {reason}")
    send_message("\n".join(lines))

def cmd_train(train_fn, count_samples: int = None):
    train_fn()
    msg = "♻ Модель переобучена"
    if count_samples:
        msg += f"\n📊 Обучено на: {count_samples} записях"
    send_message(msg)

# --- /test: быстрый пинг + картинка ---
def cmd_test(symbol="BTC/USDT"):
    send_message(f"🛠 Тест-сигнал для {symbol}")
    try:
        idx = pd.date_range(end=datetime.now(), periods=30, freq="T")
        df = pd.DataFrame({"close": [100 + i*0.2 for i in range(len(idx))]}, index=idx)
        send_chart(df, entry=df["close"].iloc[-10], exit_=df["close"].iloc[-1], title=f"Test {symbol}")
    except Exception as e:
        logging.error(f"cmd_test error: {e}")
        send_message("⚠️ Ошибка генерации тест-графика")

# -------------------- Совместимость со старым main.py --------------------
class TelegramBot:
    """
    Старый main.py делает:
        from telegram.bot_handler import TelegramBot
    Держим тонкую обёртку, чтобы импорт не падал.
    """
    def __init__(self, token: str = None, chat_id: str = None, state_manager=None):
        if token:
            os.environ['BOT_TOKEN'] = token
        if chat_id:
            os.environ['CHAT_ID'] = str(chat_id)
        self.state = state_manager

    def send_message(self, text: str, parse_mode: str = None):
        send_message(text, parse_mode=parse_mode)
