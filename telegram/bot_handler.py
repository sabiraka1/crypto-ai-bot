import os
import io
import logging
import requests
import pandas as pd
from typing import Optional, Callable, List

# headless charts
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analysis import scoring_engine
# ❌ ВАЖНО: не импортируем PositionManager сверху – избегаем циклического импорта
from trading.exchange_client import ExchangeClient

# ========= ENV / Telegram API =========
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

def _tg_request(method: str, data: dict, files: Optional[dict] = None) -> None:
    if not TELEGRAM_API or not CHAT_ID:
        logging.warning("Telegram not configured (BOT_TOKEN/CHAT_ID).")
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

# ========= СЕРВИСНЫЕ КОМАНДЫ (НУЖНЫ app.py) =========

def cmd_start() -> None:
    send_message(
        "🚀 Торговый бот запущен и готов к работе!\n\n"
        "/status – состояние позиции\n"
        "/profit – суммарный PnL\n"
        "/errors – последние ошибки\n"
        "/lasttrades – 5 последних сделок\n"
        "/train – переобучить модель\n"
        "/test – тест-сигнал\n"
        "/testbuy – ручной вход\n"
        "/testsell – ручной выход"
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
        last = price_getter()  # функция из app.py
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
    # Упрощённо: если есть файл с закрытыми сделками – считаем PnL и winrate, иначе – сообщение
    path = "closed_trades.csv"
    if not os.path.exists(path):
        send_message("📊 PnL: 0.00\nWinrate: 0.0%\nclosed_trades.csv ещё не создан")
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
        send_message(f"⚠️ Не удалось посчитать PnL: {e}")

def cmd_errors() -> None:
    # Простой вывод последних строк из лога ошибок, если есть
    path = "bot_activity.log"
    if not os.path.exists(path):
        send_message("Журнал ещё не создан")
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-15:]
        send_message("Последние сообщения лога:\n" + "".join(lines[-10:])[-3500:])
    except Exception as e:
        send_message(f"⚠️ Не удалось прочитать лог: {e}")

def cmd_lasttrades() -> None:
    path = "closed_trades.csv"
    if not os.path.exists(path):
        send_message("Сделок ещё нет")
        return
    try:
        df = pd.read_csv(path).tail(5)
        rows: List[str] = []
        for _, r in df.iterrows():
            side = str(r.get("side", "LONG"))
            e = float(r.get("entry_price", 0.0))
            x = float(r.get("exit_price", 0.0))
            reason = str(r.get("reason", ""))
            rows.append(f"- {side} {e:.1f}->{x:.1f} | {reason}")
        send_message("📋 Последние сделки:\n" + "\n".join(rows))
    except Exception as e:
        send_message(f"⚠️ Не удалось прочитать сделки: {e}")

def cmd_train(train_fn: Callable[[], bool]) -> None:
    ok = False
    try:
        ok = bool(train_fn())
    except Exception as e:
        logging.error("train_fn error: %s", e)
    send_message("✅ Модель переобучена" if ok else "ℹ️ AdaptiveMLModel: пропустил обучение (нужны X, y).")

# ========= УВЕДОМЛЕНИЯ ВХОД/ВЫХОД/ПРОПУСК =========
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

def notify_skip_entry(symbol: str, reason: str, buy_score: float, ai_score: float, min_buy: float):
    send_message(
        "⏸ Вход пропущен\n"
        f"{symbol}\n"
        f"Причина: {reason}\n"
        f"Buy {buy_score:.2f} (мин {min_buy:.2f}) | AI {ai_score:.2f}"
    )

# ========= КОРОТКОЕ ОБЪЯСНЕНИЕ СИГНАЛА (для main.py) =========
def explain_signal_short(rsi: float, adx: float, macd_hist: float, ema_fast_above: bool) -> str:
    if rsi is None:
        rsi_note = "RSI: n/a"
    elif rsi < 30:
        rsi_note = f"RSI {rsi:.1f} (перепродан)"
    elif rsi > 70:
        rsi_note = f"RSI {rsi:.1f} (перекуплен)"
    elif 45 <= rsi <= 65:
        rsi_note = f"RSI {rsi:.1f} (здоровая зона)"
    else:
        rsi_note = f"RSI {rsi:.1f}"

    if macd_hist is None:
        macd_note = "MACD hist n/a"
    else:
        macd_note = "MACD hist {:.4f} ({})".format(macd_hist, "бычий" if macd_hist > 0 else "медвежий")

    trend_note = "EMA12>EMA26" if ema_fast_above else "EMA12<=EMA26"
    adx_note = "ADX: n/a" if adx is None else f"ADX {adx:.1f}"
    return f"{rsi_note} | {macd_note} | {trend_note} | {adx_note}"

# ========= TEST: краткий анализ без сделки =========
def cmd_test(symbol: str = None, timeframe: str = None):
    symbol = symbol or os.getenv("SYMBOL", "BTC/USDT")
    timeframe = timeframe or os.getenv("TIMEFRAME", "15m")
    try:
        ex = ExchangeClient()
        ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=200)
        if not ohlcv:
            send_message(f"⚠️ Нет данных OHLCV для {symbol}")
            return
        df = pd.DataFrame(ohlcv, columns=["time","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df.set_index("time", inplace=True)

        engine = scoring_engine.ScoringEngine()
        buy_score, ai_score, _ = engine.score(df)
        last = ex.get_last_price(symbol)
        send_message(f"🧪 TEST {symbol}\nЦена: {last:.2f}\nBuy {buy_score:.2f} | AI {ai_score:.2f}")

        # чарт
        try:
            plt.figure(figsize=(10,4))
            df["close"].plot()
            plt.title(f"TEST {symbol} — close")
            plt.tight_layout()
            plt.savefig("test_chart.png", dpi=120)
            plt.close()
            send_photo("test_chart.png")
        except Exception:
            logging.exception("chart error")
    except Exception as e:
        logging.exception("cmd_test error")
        send_message(f"❌ TEST ошибка: {e}")

# ========= ТЕСТОВЫЕ КОМАНДЫ (ручной вход/выход) =========
def cmd_testbuy(state_manager, exchange_client, symbol: str = None, amount_usd: float = None):
    """
    Принудительно открыть LONG. Сумма берётся из аргумента или TRADE_AMOUNT (.env, дефолт 50).
    """
    # локальный импорт, чтобы не ловить цикл импорта
    from trading.position_manager import PositionManager

    symbol = symbol or os.getenv("SYMBOL", "BTC/USDT")
    if amount_usd is None:
        try:
            amount_usd = float(os.getenv("TRADE_AMOUNT", "50"))
        except Exception:
            amount_usd = 50.0

    pm = PositionManager(exchange_client, state_manager)
    try:
        last = exchange_client.get_last_price(symbol)
        # оценим Buy/AI для уведомления
        try:
            ohlcv = exchange_client.fetch_ohlcv(symbol, timeframe=os.getenv("TIMEFRAME","15m"), limit=200)
            df = pd.DataFrame(ohlcv, columns=["time","open","high","low","close","volume"])
            df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
            df.set_index("time", inplace=True)
            engine = scoring_engine.ScoringEngine()
            buy_score, ai_score, _ = engine.score(df)
        except Exception:
            buy_score, ai_score = None, None

        pm.open_long(symbol, amount_usd, last, atr=0.0, buy_score=buy_score, ai_score=ai_score)
        send_message(f"✅ TESTBUY выполнен: {symbol} на ${amount_usd:.2f}")
    except Exception as e:
        logging.error(f"cmd_testbuy error: {e}")
        send_message(f"❌ TESTBUY ошибка: {e}")

def cmd_testsell(state_manager, exchange_client, symbol: str = None):
    """Принудительно закрыть позицию по рынку."""
    from trading.position_manager import PositionManager  # локальный импорт
    symbol = symbol or os.getenv("SYMBOL", "BTC/USDT")
    pm = PositionManager(exchange_client, state_manager)
    try:
        last = exchange_client.get_last_price(symbol)
        pm.close_all(symbol, last, reason="manual_testsell")
        send_message(f"✅ TESTSELL выполнен: {symbol}")
    except Exception as e:
        logging.error(f"cmd_testsell error: {e}")
        send_message(f"❌ TESTSELL ошибка: {e}")
