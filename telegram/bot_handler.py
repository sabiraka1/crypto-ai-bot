import os
import io
import logging
import requests
import pandas as pd
from datetime import datetime
from typing import Optional

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
    if entry: plt.axhline(entry, linestyle="--", color="green")
    if exit_: plt.axhline(exit_, linestyle=":", color="red")
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

# -------------------- команды --------------------
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
    TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", "50"))
    total_pnl = 0.0
    winrate = 0.0
    lines = []

    if os.path.exists(closed_csv_path):
        try:
            df = pd.read_csv(closed_csv_path)
            if not df.empty and {"entry_price", "close_price"}.issubset(df.columns):
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
                lines.extend(raw[-5:])
        except Exception as e:
            logging.error(f"cmd_profit read log error: {e}")
            lines.append("⚠️ Не удалось прочитать trades.log")

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
        lines.append(f"- {r.get('time', '')} | RSI {r.get('rsi', '')} | MACD {r.get('macd', '')}")
    send_message("\n".join(lines))

def cmd_lasttrades(closed_csv_path="closed_trades.csv"):
    if not os.path.exists(closed_csv_path):
        send_message("📭 Сделок ещё нет"); return
    df = pd.read_csv(closed_csv_path).tail(5)
    if df.empty:
        send_message("📭 Сделок ещё нет"); return
    lines = ["🧾 Последние сделки:"]
    for _, r in df.iterrows():
        lines.append(f"- {r.get('time', r.get('close_time', ''))} | {r.get('side', 'LONG')} {r.get('entry_price', '')}→{r.get('close_price', '')} | {r.get('reason', r.get('close_reason', ''))}")
    send_message("\n".join(lines))

def cmd_train(train_fn, count_samples: int = None):
    train_fn()
    msg = "♻ Модель переобучена"
    if count_samples:
        msg += f"\n📊 Обучено на: {count_samples} записях"
    send_message(msg)

# ---------- новый /test ----------
def cmd_test(symbol="BTC/USDT"):
    send_message(f"🛠 Тест-сигнал для {symbol}")
    # тут можно сделать генерацию случайных значений для RSI/MACD и графика
    try:
        df = pd.DataFrame({"close": [100, 102, 101, 103, 104]}, index=pd.date_range(end=datetime.now(), periods=5, freq="T"))
        send_chart(df, entry=102, exit_=104, title=f"Test {symbol}")
    except Exception as e:
        logging.error(f"cmd_test error: {e}")
        send_message("⚠️ Ошибка генерации тест-графика")
