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
from trading.position_manager import PositionManager  # для testbuy/testsell
from core.state_manager import StateManager
from utils.csv_handler import CSVHandler  # <-- новый импорт

# ==== ENV ====
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

SYMBOL_ENV = os.getenv("SYMBOL", "BTC/USDT")
TIMEFRAME_ENV = os.getenv("TIMEFRAME", "15m")
TEST_TRADE_AMOUNT = float(os.getenv("TEST_TRADE_AMOUNT", os.getenv("TRADE_AMOUNT", "3")))
# Примечание: min_notional по символу учитывается на уровне ExchangeClient/PositionManager


# ==== Telegram helpers ====
def _tg_request(method: str, data: dict, files: Optional[dict] = None) -> None:
    if not TELEGRAM_API or not CHAT_ID:
        logging.warning("Telegram not configured (BOT_TOKEN/CHAT_ID missing)")
        return
    url = f"{TELEGRAM_API}/{method}"
    try:
        resp = requests.post(url, data=data, files=files, timeout=15)
        if resp.status_code != 200:
            logging.error("Telegram API error: %s %s", resp.status_code, resp.text[:200])
        else:
            logging.info("[TG] %s ok: %s", method, resp.text[:120])
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


# ==== Notifications for trades (совместимо с PositionManager.notify_*) ====
def notify_entry(symbol: str, side: str, price: float, amount: float, reason: str = "") -> None:
    msg = (
        f"📈 Открыта {side.upper()} позиция\n"
        f"Инструмент: {symbol}\n"
        f"Цена входа: {price:.4f}\n"
        f"Объём: {amount}\n"
    )
    if reason:
        msg += f"Причина: {reason}"
    send_message(msg)

def notify_close(symbol: str, side: str, entry_price: float, exit_price: float,
                 pnl_abs: float, pnl_pct: float, reason: str = "") -> None:
    emoji = "✅" if pnl_pct >= 0 else "❌"
    msg = (
        f"{emoji} Закрыта {side.upper()} позиция\n"
        f"{symbol}\n"
        f"Вход: {entry_price:.4f} → Выход: {exit_price:.4f}\n"
        f"PnL: {pnl_abs:.2f} USDT ({pnl_pct:.2f}%)\n"
    )
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
        "/testbuy – Тестовая покупка (через PositionManager)\n"
        "/testsell – Тестовая продажа (закрыть позицию через PositionManager)"
    )

def cmd_status(state_manager: StateManager, price_getter: Callable[[], Optional[float]]) -> None:
    st = getattr(state_manager, "state", {}) or {}
    if not st.get("in_position"):
        send_message("🟢 Позиции нет")
        return
    sym = st.get("symbol", SYMBOL_ENV)
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
    tp1_atr = st.get("tp1_atr")
    tp2_atr = st.get("tp2_atr")
    sl_atr = st.get("sl_atr")
    flags = []
    if tp and sl:
        txt.append(f"TP≈{tp:.4f} | SL≈{sl:.4f}")
    if tp1_atr:
        flags.append(f"TP1≈{float(tp1_atr):.4f}")
    if tp2_atr:
        flags.append(f"TP2≈{float(tp2_atr):.4f}")
    if sl_atr:
        flags.append(f"SL_ATR≈{float(sl_atr):.4f}")
    if st.get("trailing_on"):
        flags.append("trailing ON")
    if st.get("partial_taken"):
        flags.append("partial taken")
    if flags:
        txt.append(" | ".join(flags))

    send_message("\n".join(txt))

def cmd_profit() -> None:
    path = os.getenv("CLOSED_TRADES_CSV", "closed_trades.csv")
    if not os.path.exists(path):
        send_message("📊 PnL: 0.00\nWinrate: 0.0%\nТрейдов: 0")
        return
    try:
        df = CSVHandler.read_csv_safe(path)
        if df is None or df.empty:
            send_message("📊 PnL: 0.00\nWinrate: 0.0%\nТрейдов: 0")
            return
        # приведение типов
        if "pnl_abs" in df.columns:
            df["pnl_abs"] = pd.to_numeric(df["pnl_abs"], errors="coerce").fillna(0.0)
        else:
            df["pnl_abs"] = 0.0
        if "pnl_pct" in df.columns:
            df["pnl_pct"] = pd.to_numeric(df["pnl_pct"], errors="coerce")
        else:
            df["pnl_pct"] = pd.Series(dtype=float)

        pnl = float(df["pnl_abs"].sum())
        wins = int((df["pnl_pct"] > 0).sum())
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
    try:
        rows = CSVHandler.read_last_trades(limit=5)
        if not rows:
            send_message("Сделок ещё нет")
            return
        lines: List[str] = []
        for r in rows:
            side = str(r.get("side") or "BUY")
            e = r.get("entry_price")
            x = r.get("exit_price")
            pnl_pct = r.get("pnl_pct")
            reason = str(r.get("reason") or "")
            ai = r.get("ai_score")
            bs = r.get("buy_score")
            fs = r.get("final_score")
            base = f"- {side} {e if e=='' else f'{float(e):.4f}'} → {x if x=='' else f'{float(x):.4f}'}"
            extras = []
            if pnl_pct not in ("", None):
                try:
                    extras.append(f"{float(pnl_pct):.2f}%")
                except Exception:
                    pass
            if reason:
                extras.append(reason)
            if bs not in ("", None) or ai not in ("", None):
                pair = []
                if bs not in ("", None):
                    pair.append(f"B:{float(bs):.2f}" if bs != "" else "")
                if ai not in ("", None):
                    pair.append(f"AI:{float(ai):.2f}" if ai != "" else "")
                extras.append(" ".join([p for p in pair if p]))
            if fs not in ("", None):
                extras.append(f"F:{float(fs):.2f}")
            if extras:
                base += " | " + " | ".join(extras)
            lines.append(base)
        send_message("📋 Последние сделки:\n" + "\n".join(lines))
    except Exception as e:
        logging.exception("cmd_lasttrades error")
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

# ==== Helpers ====
def _ohlcv_to_df(ohlcv) -> pd.DataFrame:
    if not ohlcv:
        return pd.DataFrame()
    cols = ["time", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(ohlcv, columns=cols)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.set_index("time", inplace=True)
    return df

def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if df.empty or len(df) < period + 2:
        return 0.0
    high = df["high"]; low = df["low"]; close = df["close"]; prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1/period, adjust=False).mean().iloc[-1])

# ==== Test commands (через PositionManager) ====
def cmd_test(symbol: str = None, timeframe: str = None):
    symbol = symbol or SYMBOL_ENV
    timeframe = timeframe or TIMEFRAME_ENV
    try:
        ex = ExchangeClient()
        ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=200)
        if not ohlcv:
            send_message(f"⚠️ Нет данных OHLCV для {symbol}")
            return
        df = _ohlcv_to_df(ohlcv)

        engine = scoring_engine.ScoringEngine()
        scores = engine.calculate_scores(df) if hasattr(engine, "calculate_scores") \
                 else engine.evaluate(df, ai_score=0.55)
        if isinstance(scores, tuple) and len(scores) >= 2:
            buy_score, ai_score = float(scores[0]), float(scores[1])
        else:
            buy_score, ai_score = 0.0, 0.55

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

def cmd_testbuy(state_manager: StateManager, exchange_client: ExchangeClient, amount_usd: float = None):
    symbol = SYMBOL_ENV
    try:
        amount = float(amount_usd if amount_usd is not None else TEST_TRADE_AMOUNT)
    except Exception:
        amount = TEST_TRADE_AMOUNT

    try:
        ohlcv = exchange_client.fetch_ohlcv(symbol, timeframe=TIMEFRAME_ENV, limit=200)
        df = _ohlcv_to_df(ohlcv)
        last = float(df["close"].iloc[-1]) if not df.empty else exchange_client.get_last_price(symbol)
        atr_val = _atr(df)

        pm = PositionManager(exchange_client, state_manager, notify_entry_func=None, notify_close_func=None)
        res = pm.open_long(symbol, amount, entry_price=last, atr=atr_val or 0.0,
                           buy_score=None, ai_score=None, amount_frac=None)
        if res is None:
            send_message("⏭️ Покупка пропущена (возможно, уже есть позиция или ошибка). См. логи.")
        else:
            min_cost = exchange_client.market_min_cost(symbol) or 0.0
            send_message(f"🧪 TEST BUY {symbol}: запрошено ${amount:.2f} (min_cost {min_cost:.2f}). "
                         f"Статус: {'paper' if res.get('paper') else 'real'} | id={res.get('id','-')}")
    except Exception as e:
        logging.exception("cmd_testbuy error")
        send_message(f"❌ TEST BUY ошибка: {e}")

def cmd_testsell(state_manager: StateManager, exchange_client: ExchangeClient):
    symbol = SYMBOL_ENV
    try:
        last = None
        try:
            last = float(exchange_client.get_last_price(symbol))
        except Exception:
            last = 0.0
        pm = PositionManager(exchange_client, state_manager, notify_entry_func=None, notify_close_func=None)
        res = pm.close_all(symbol, exit_price=(last or 0.0), reason="manual_test")
        if res is None:
            send_message("⏭️ Продажа пропущена (возможно, позиции нет).")
        else:
            send_message(f"🧪 TEST SELL {symbol}: попытка закрыть позицию. См. логи.")
    except Exception as e:
        logging.exception("cmd_testsell error")
        send_message(f"❌ TEST SELL ошибка: {e}")


# ==== Router ====
def process_command(text: str, state_manager, exchange_client: ExchangeClient, train_func: Optional[Callable] = None):
    text = (text or "").strip()
    if not text.startswith("/"):
        return
    try:
        sym = SYMBOL_ENV
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
        if text.startswith("/test "):
            parts = text.split()
            s = parts[1] if len(parts) > 1 else None
            tf = parts[2] if len(parts) > 2 else None
            return cmd_test(s, tf)
        if text.strip() == "/test":
            return cmd_test()
        if text.startswith("/testbuy"):
            parts = text.split()
            amt = float(parts[1]) if len(parts) > 1 else None
            return cmd_testbuy(state_manager, exchange_client, amt)
        if text.startswith("/testsell"):
            return cmd_testsell(state_manager, exchange_client)

        logging.info(f"Unknown or unsupported command: {text}")
        send_message(f"❓ Неизвестная команда: {text}")
    except Exception as e:
        logging.exception(f"process_command error: {e}")
        send_message(f"⚠️ Ошибка обработки команды: {e}")
