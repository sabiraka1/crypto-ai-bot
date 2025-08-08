import os
import io
import logging
import requests
import pandas as pd
from typing import Optional, Callable

# headless charts
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analysis import scoring_engine
from trading.position_manager import PositionManager

# ========= ENV / Telegram API =========
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def _post(method: str, **payload):
    try:
        r = requests.post(f"{API}/{method}", json=payload, timeout=20)
        r.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"Telegram API error: {e}")
        return False

def send_message(text: str, parse_mode: Optional[str] = None):
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning("Telegram not configured (BOT_TOKEN/CHAT_ID missing)")
        return
    data = {"chat_id": CHAT_ID, "text": text}
    if parse_mode:
        data["parse_mode"] = parse_mode
    _post("sendMessage", **data)

def send_photo_bytes(img: bytes, caption: str = ""):
    if not BOT_TOKEN or not CHAT_ID:
        return
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


# ========= Команды =========
def cmd_start():
    send_message(
        "🤖 Crypto AI Bot\n"
        "/status – состояние позиции\n"
        "/profit – суммарный PnL\n"
        "/errors – последние ошибки\n"
        "/lasttrades – 5 последних сделок\n"
        "/train – переобучить модель\n"
        "/test – краткий анализ сигнала\n"
        "/testbuy – открыть LONG (тест)\n"
        "/testsell – закрыть позицию (тест)"
    )

def cmd_status(state_manager, get_price_fn: Callable[[], float], symbol: str = "BTC/USDT"):
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
            f"📈 LONG открыта {symbol}\n"
            f"Вход: {st.get('entry_price')} | TP: {st.get('tp_price_pct')} | SL: {st.get('sl_price_pct')}\n"
            f"Текущая: {last} | PnL: {pnl:.2f}%"
        )
    else:
        send_message("🟢 Позиции нет")

def cmd_profit(closed_csv_path="closed_trades.csv"):
    if not os.path.exists(closed_csv_path):
        send_message("📭 Сделок ещё нет"); return
    df = pd.read_csv(closed_csv_path)
    if df.empty:
        send_message("📭 Сделок ещё нет"); return
    if "pnl_abs" in df.columns:
        pnl = df["pnl_abs"].sum()
        winrate = (df["pnl_abs"] > 0).mean() * 100
    else:
        # fallback без qty: просто разница цен
        df["pnl_abs"] = (df["close_price"] - df["entry_price"])
        pnl = df["pnl_abs"].sum()
        winrate = (df["pnl_abs"] > 0).mean() * 100
    send_message(f"💰 PnL: {pnl:.2f}\nWinrate: {winrate:.1f}%")

def cmd_errors(csv_path="sinyal_fiyat_analizi.csv"):
    if not os.path.exists(csv_path):
        send_message("❌ Нет данных ошибок"); return
    df = pd.read_csv(csv_path)
    if "result" not in df.columns:
        send_message("ℹ️ Лог сигналов ещё не размечен колонкой 'result'"); return
    bad = df[df["result"] == 0].tail(5)
    if bad.empty:
        send_message("✅ Ошибок нет"); return
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
    try:
        train_fn()
        msg = "♻ Модель переобучена"
        if count_samples:
            msg += f"\n📊 Обучено на: {count_samples} записях"
        send_message(msg)
    except Exception as e:
        logging.error(f"/train error: {e}")
        send_message("⚠️ Обучение пропущено (нужны данные X,y)")

# ====== уведомления вход/выход/пропуск ======
def notify_entry(symbol: str, price: float, amount_usd: float, tp: float, sl: float, tp1: float, tp2: float,
                 buy_score: float = None, ai_score: float = None, amount_frac: float = None):
    expl = []
    if buy_score is not None and ai_score is not None:
        expl.append(f"Buy {buy_score:.2f} / AI {ai_score:.2f}")
    if amount_frac is not None:
        expl.append(f"Size {int(amount_frac*100)}%")
    send_message(
        "📥 Вход LONG {sym} @ {pr}\n{info}\nСумма: ${amt}\nTP%: {tp:.2f} | SL%: {sl:.2f}\nTP1: {tp1:.2f} | TP2: {tp2:.2f}"
        .format(sym=symbol, pr=price, info=" | ".join(expl) if expl else "", amt=amount_usd, tp=tp, sl=sl, tp1=tp1, tp2=tp2)
    )

def notify_close(symbol: str, price: float, reason: str, pnl_pct: float, pnl_abs: float = None):
    base = f"📤 Закрытие {symbol} @ {price}\n{reason} | PnL {pnl_pct:.2f}%"
    if pnl_abs is not None:
        base += f" ({pnl_abs:.2f}$)"
    send_message(base)

def notify_skip_entry(symbol: str, reason: str, buy_score: float, ai_score: float, min_buy: float):
    send_message(
        "⏸ Вход пропущен\n"
        f"{symbol}\n"
        f"Причина: {reason}\n"
        f"Buy {buy_score:.2f} (мин {min_buy:.2f}) | AI {ai_score:.2f}"
    )


# ====== Тестовые команды ======
def cmd_testbuy(state_manager, exchange_client, symbol: str = None, amount_usd: float = None):
    """
    Принудительно открыть LONG (для проверки всей цепочки).
    Если amount_usd не передан — берём TRADE_AMOUNT из .env (или 50).
    """
    symbol = symbol or os.getenv("SYMBOL", "BTC/USDT")
    if amount_usd is None:
        try:
            amount_usd = float(os.getenv("TRADE_AMOUNT", "50"))
        except Exception:
            amount_usd = 50.0

    pm = PositionManager(exchange_client, state_manager)
    try:
        last = exchange_client.get_last_price(symbol)
        pm.open_long(symbol, amount_usd, last, atr=0.0)
        send_message(f"✅ TESTBUY выполнен: {symbol} на ${amount_usd}")
    except Exception as e:
        logging.error(f"cmd_testbuy error: {e}")
        send_message(f"❌ TESTBUY ошибка: {e}")

def cmd_testsell(state_manager, exchange_client, symbol: str = None):
    """
    Принудительно закрыть позицию по рынку (для проверки).
    """
    symbol = symbol or os.getenv("SYMBOL", "BTC/USDT")
    pm = PositionManager(exchange_client, state_manager)
    try:
        last = exchange_client.get_last_price(symbol)
        pm.close_all(symbol, last, reason="manual_testsell")
        send_message(f"✅ TESTSELL выполнен: {symbol}")
    except Exception as e:
        logging.error(f"cmd_testsell error: {e}")
        send_message(f"❌ TESTSELL ошибка: {e}")
