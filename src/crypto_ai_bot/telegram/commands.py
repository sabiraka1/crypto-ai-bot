import os
import logging
import time
from typing import Optional, Callable, List
from crypto_ai_bot.core.events import EventBus

import pandas as pd

from crypto_ai_bot.analysis import scoring_engine
from crypto_ai_bot.trading.exchange_client import ExchangeClient
from crypto_ai_bot.core.state_manager import StateManager
from crypto_ai_bot.utils.csv_handler import CSVHandler
from crypto_ai_bot.core.settings import Settings

from .api_utils import send_message, send_photo, ADMIN_CHAT_IDS

# РњСЏРіРєРёР№ РёРјРїРѕСЂС‚ РіСЂР°С„РёРєРѕРІ: СЃРµСЂРІРёСЃ РїРѕРґРЅРёРјРµС‚СЃСЏ РґР°Р¶Рµ РµСЃР»Рё matplotlib РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ
try:
    from .charts import generate_price_chart, CHARTS_READY
except Exception:
    generate_price_chart = None
    CHARTS_READY = False

# в”Ђв”Ђ РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
CFG = Settings.load()
SYMBOL_ENV = CFG.SYMBOL
TIMEFRAME_ENV = CFG.TIMEFRAME
TRADE_AMOUNT = CFG.POSITION_SIZE_USD

# ==== Anti-spam settings ====
_last_command_time = {}
COMMAND_COOLDOWN = CFG.COMMAND_COOLDOWN


def anti_spam(user_id):
    now = time.time()
    if user_id in _last_command_time and now - _last_command_time[user_id] < COMMAND_COOLDOWN:
        return False
    _last_command_time[user_id] = now
    return True


def is_authorized(chat_id: str) -> bool:
    if not ADMIN_CHAT_IDS:
        return True
    return str(chat_id) in ADMIN_CHAT_IDS


def safe_command(func):
    def wrapper(*args, **kwargs):
        chat_id = None
        try:
            if args and isinstance(args[0], dict):
                chat_id = args[0].get("message", {}).get("chat", {}).get("id")
            elif len(args) > 1 and isinstance(args[1], (str, int)):
                chat_id = str(args[1])
        except Exception:
            pass

        if chat_id and not is_authorized(chat_id):
            logging.warning(f"вќЊ Unauthorized access attempt from chat_id: {chat_id}")
            send_message("вќЊ РЈ РІР°СЃ РЅРµС‚ РїСЂР°РІ РґР»СЏ РІС‹РїРѕР»РЅРµРЅРёСЏ РєРѕРјР°РЅРґ.", chat_id=str(chat_id))
            return

        if chat_id and not anti_spam(chat_id):
            send_message("вЏі РџРѕРґРѕР¶РґРё РїР°СЂСѓ СЃРµРєСѓРЅРґ РїРµСЂРµРґ СЃР»РµРґСѓСЋС‰РµР№ РєРѕРјР°РЅРґРѕР№.", chat_id=str(chat_id))
            return

        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.exception(f"РћС€РёР±РєР° РІ РєРѕРјР°РЅРґРµ {func.__name__}: {e}")
            if chat_id:
                send_message("вљ пёЏ РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё РІС‹РїРѕР»РЅРµРЅРёРё РєРѕРјР°РЅРґС‹.", chat_id=str(chat_id))
    return wrapper


# ==== Helpers (CSV Р±РµР·РѕРїР°СЃРЅС‹Рµ С„РѕР»Р±СЌРєРё) ====

def _read_csv_safe(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    try:
        return pd.read_csv(path).to_dict("records")
    except Exception as e:
        logging.error(f"read_csv_safe failed: {e}")
        return []

def _read_last_trades(limit: int = 5) -> List[dict]:
    rows = _read_csv_safe(CFG.CLOSED_TRADES_CSV)
    return rows[-limit:] if rows else []


# ==== Unified ATR for telegram ====

def _atr(df: pd.DataFrame, period: int = 14) -> float:
    try:
        from crypto_ai_bot.core.indicators.unified import get_unified_atr
        result = float(get_unified_atr(df, period, method="ewm"))
        logging.debug(f"рџ“Љ Telegram ATR (UNIFIED): {result:.6f}")
        return result
    except Exception as e:
        logging.error(f"UNIFIED ATR failed in telegram: {e}")
        try:
            return float((df["high"] - df["low"]).mean()) if not df.empty else 0.0
        except Exception:
            return 0.0


def _ohlcv_to_df(ohlcv) -> pd.DataFrame:
    if not ohlcv:
        return pd.DataFrame()
    cols = ["time", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(ohlcv, columns=cols)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.set_index("time", inplace=True)
    # РїСЂРёРІРѕРґРёРј Рє С‡РёСЃР»Р°Рј РїРѕ РІРѕР·РјРѕР¶РЅРѕСЃС‚Рё
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna()


# ==== Commands ===============================================================

@safe_command
def cmd_start(chat_id: str = None) -> None:
    send_message(
        "рџљЂ РўРѕСЂРіРѕРІС‹Р№ Р±РѕС‚ Р·Р°РїСѓС‰РµРЅ!\n\n"
        "рџ“‹ Р”РѕСЃС‚СѓРїРЅС‹Рµ РєРѕРјР°РЅРґС‹:\n"
        "/status вЂ“ РџРѕРєР°Р·Р°С‚СЊ РѕС‚РєСЂС‹С‚СѓСЋ РїРѕР·РёС†РёСЋ\n"
        "/profit вЂ“ РћР±С‰РёР№ PnL Рё Winrate\n"
        "/lasttrades вЂ“ РџРѕСЃР»РµРґРЅРёРµ СЃРґРµР»РєРё\n"
        "/test вЂ“ РўРµСЃС‚ СЃРёРіРЅР°Р»Р° СЃ ATR Р°РЅР°Р»РёР·РѕРј\n"
        "/testbuy [СЃСѓРјРјР°] вЂ“ РўРµСЃС‚РѕРІР°СЏ РїРѕРєСѓРїРєР°\n"
        "/testsell вЂ“ РўРµСЃС‚РѕРІР°СЏ РїСЂРѕРґР°Р¶Р°\n"
        "/help вЂ“ РЎРїСЂР°РІРєР° РїРѕ РєРѕРјР°РЅРґР°Рј\n"
        "/errors вЂ“ РџРѕСЃР»РµРґРЅРёРµ РѕС€РёР±РєРё\n"
        "/train вЂ“ РћР±СѓС‡РёС‚СЊ AI РјРѕРґРµР»СЊ\n\n"
        "вњ… UNIFIED ATR СЃРёСЃС‚РµРјР° Р°РєС‚РёРІРЅР°",
        chat_id,
    )


@safe_command
def cmd_status(state_manager: StateManager, exchange_client: ExchangeClient, chat_id: str = None) -> None:
    try:
        st = getattr(state_manager, "state", {}) or {}
        if not st.get("in_position"):
            send_message("рџџў РџРѕР·РёС†РёРё РЅРµС‚", chat_id)
            return

        sym = st.get("symbol", SYMBOL_ENV)
        entry = float(st.get("entry_price") or 0.0)

        try:
            current_price = exchange_client.get_last_price(sym)
        except Exception as e:
            logging.error(f"Failed to get current price: {e}")
            current_price = None

        lines = []
        if current_price:
            pnl_pct = (current_price - entry) / entry * 100.0 if entry else 0.0
            emoji = "рџ“€" if pnl_pct >= 0 else "рџ“‰"
            lines.append(f"{emoji} Advanced LONG {sym} @ {entry:.2f}")
        else:
            lines.append(f"рџ“Њ LONG {sym} @ {entry:.2f}")

        qty_usd = st.get("qty_usd")
        if qty_usd:
            lines.append(f"РЎСѓРјРјР°: ${float(qty_usd):.2f}")

        if current_price:
            pnl_pct = (current_price - entry) / entry * 100.0 if entry else 0.0
            pnl_abs = (current_price - entry) * st.get("qty_base", 0)
            pnl_emoji = "рџџў" if pnl_pct >= 0 else "рџ”ґ"
            lines.append(f"РўРµРєСѓС‰Р°СЏ: {current_price:.2f}")
            lines.append(f"{pnl_emoji} PnL: {pnl_pct:+.2f}% (${pnl_abs:+.2f})")

        sl = st.get("sl_atr")
        tp1 = st.get("tp1_atr")
        if sl:
            lines.append(f"рџ”µ Dynamic SL: {float(sl):.2f}")
        if tp1:
            lines.append(f"рџ”¶ Next TP: {float(tp1):.2f}")

        buy_score = st.get("buy_score")
        ai_score = st.get("ai_score")
        amount_frac = st.get("amount_frac", 1.0)

        score_parts = []
        if buy_score is not None and ai_score is not None:
            score_parts.append(f"Score {float(buy_score):.1f} / AI {float(ai_score):.2f}")
        if amount_frac:
            size_pct = int(float(amount_frac) * 100)
            score_parts.append(f"Size {size_pct}%")

        flags = []
        if st.get("partial_taken"):
            flags.append("Multi-TP ON")
        if st.get("trailing_on"):
            flags.append("Dynamic SL ON")

        if score_parts or flags:
            lines.append(" | ".join(score_parts + flags))

        send_message("\n".join(lines), chat_id)

    except Exception as e:
        logging.exception("cmd_status error")
        send_message(f"вљ пёЏ РћС€РёР±РєР° РїСЂРё РїРѕР»СѓС‡РµРЅРёРё СЃС‚Р°С‚СѓСЃР°: {e}", chat_id)


@safe_command
def cmd_profit(chat_id: str = None) -> None:
    try:
        path = CFG.CLOSED_TRADES_CSV
        rows = _read_csv_safe(path)
        if not rows:
            send_message("рџ“Љ PnL: 0.00 USDT\nWinrate: 0.0%\nРўСЂРµР№РґРѕРІ: 0", chat_id)
            return

        df = pd.DataFrame(rows)
        df["pnl_abs"] = pd.to_numeric(df.get("pnl_abs", 0.0), errors="coerce").fillna(0.0)
        df["pnl_pct"] = pd.to_numeric(df.get("pnl_pct", 0.0), errors="coerce").fillna(0.0)

        total_pnl = float(df["pnl_abs"].sum())
        wins = int((df["pnl_pct"] > 0).sum())
        total_trades = int(len(df))
        win_rate = (wins / total_trades * 100.0) if total_trades else 0.0

        if total_trades > 0:
            avg_win = float(df[df["pnl_pct"] > 0]["pnl_pct"].mean() or 0.0)
            avg_loss = float(df[df["pnl_pct"] < 0]["pnl_pct"].mean() or 0.0)
            message = (
                f"рџ“Љ РўРѕСЂРіРѕРІР°СЏ СЃС‚Р°С‚РёСЃС‚РёРєР°:\n"
                f"рџ’° РћР±С‰РёР№ PnL: {total_pnl:.2f} USDT\n"
                f"рџ“€ Winrate: {win_rate:.1f}% ({wins}/{total_trades})\n"
                f"рџџў РЎСЂРµРґРЅРёР№ РїСЂРѕС„РёС‚: {avg_win:.2f}%\n"
                f"рџ”ґ РЎСЂРµРґРЅРёР№ СѓР±С‹С‚РѕРє: {avg_loss:.2f}%\n"
                f"рџ“Љ Р’СЃРµРіРѕ СЃРґРµР»РѕРє: {total_trades}"
            )
        else:
            message = "рџ“Љ РЎС‚Р°С‚РёСЃС‚РёРєР° РЅРµРґРѕСЃС‚СѓРїРЅР° - РЅРµС‚ Р·Р°РІРµСЂС€РµРЅРЅС‹С… СЃРґРµР»РѕРє"

        send_message(message, chat_id)

    except Exception as e:
        logging.exception("cmd_profit error")
        send_message(f"вљ пёЏ РћС€РёР±РєР° РїСЂРё СЂР°СЃС‡РµС‚Рµ СЃС‚Р°С‚РёСЃС‚РёРєРё: {e}", chat_id)


@safe_command
def cmd_lasttrades(chat_id: str = None) -> None:
    try:
        trades = _read_last_trades(limit=5)
        if not trades:
            send_message("рџ“‹ РЎРґРµР»РѕРє РµС‰С‘ РЅРµС‚", chat_id)
            return

        lines: List[str] = ["рџ“‹ РџРѕСЃР»РµРґРЅРёРµ СЃРґРµР»РєРё:"]
        for i, trade in enumerate(trades, 1):
            side = str(trade.get("side", "LONG"))
            entry = trade.get("entry_price", "")
            exit_price = trade.get("exit_price", "")
            pnl_pct = trade.get("pnl_pct", "")
            reason = str(trade.get("reason", ""))

            trade_line = f"{i}. {side}"
            if entry and exit_price:
                try:
                    trade_line += f" {float(entry):.2f}в†’{float(exit_price):.2f}"
                except (ValueError, TypeError):
                    trade_line += f" {entry}в†’{exit_price}"

            if pnl_pct != "":
                try:
                    pnl_val = float(pnl_pct)
                    emoji = "рџџў" if pnl_val >= 0 else "рџ”ґ"
                    trade_line += f" {emoji}{pnl_val:+.2f}%"
                except (ValueError, TypeError):
                    trade_line += f" {pnl_pct}%"

            if reason:
                trade_line += f" ({reason})"

            lines.append(trade_line)

        send_message("\n".join(lines), chat_id)

    except Exception as e:
        logging.exception("cmd_lasttrades error")
        send_message(f"вљ пёЏ РћС€РёР±РєР° РїСЂРё РїРѕР»СѓС‡РµРЅРёРё СЃРґРµР»РѕРє: {e}", chat_id)


@safe_command
def cmd_errors(chat_id: str = None) -> None:
    log_path = "bot_activity.log"
    if not os.path.exists(log_path):
        send_message("рџ“ќ Р›РѕРі-С„Р°Р№Р» РµС‰С‘ РЅРµ СЃРѕР·РґР°РЅ", chat_id)
        return
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        error_lines = []
        for line in reversed(lines[-100:]):
            if any(level in line for level in ["ERROR", "WARNING", "EXCEPTION"]):
                error_lines.append(line.strip())
                if len(error_lines) >= 10:
                    break

        message = (
            "рџљЁ РџРѕСЃР»РµРґРЅРёРµ РѕС€РёР±РєРё:\n" + "\n".join(reversed(error_lines))
            if error_lines else "вњ… РћС€РёР±РѕРє РІ РїРѕСЃР»РµРґРЅРёС… Р»РѕРіР°С… РЅРµ РЅР°Р№РґРµРЅРѕ"
        )
        if len(message) > 4000:
            message = message[:4000] + "..."
        send_message(message, chat_id)
    except Exception as e:
        send_message(f"вљ пёЏ РћС€РёР±РєР° С‡С‚РµРЅРёСЏ Р»РѕРіР°: {e}", chat_id)


@safe_command
def cmd_train(train_func: Callable, chat_id: str = None) -> None:
    send_message("рџ§  Р—Р°РїСѓСЃРє РѕР±СѓС‡РµРЅРёСЏ AI РјРѕРґРµР»Рё...", chat_id)
    try:
        if not train_func:
            send_message("вќЊ Р¤СѓРЅРєС†РёСЏ РѕР±СѓС‡РµРЅРёСЏ РЅРµРґРѕСЃС‚СѓРїРЅР°", chat_id)
            return

        success = train_func()
        send_message("вњ… AI РјРѕРґРµР»СЊ СѓСЃРїРµС€РЅРѕ РѕР±СѓС‡РµРЅР°!" if success else "вќЊ РћС€РёР±РєР° РїСЂРё РѕР±СѓС‡РµРЅРёРё РјРѕРґРµР»Рё", chat_id)
    except Exception as e:
        logging.exception("cmd_train error")
        send_message(f"вќЊ РћС€РёР±РєР° РѕР±СѓС‡РµРЅРёСЏ: {e}", chat_id)


@safe_command
def cmd_test(symbol: str = None, timeframe: str = None, chat_id: str = None):
    symbol = symbol or SYMBOL_ENV
    timeframe = timeframe or TIMEFRAME_ENV
    try:
        ex = ExchangeClient(CFG)  # РёСЃРїРѕР»СЊР·СѓРµРј РѕР±С‰РёР№ РєР»РёРµРЅС‚
        ohlcv = ex.get_ohlcv(symbol, timeframe=timeframe, limit=200)
        if not ohlcv:
            send_message(f"вљ пёЏ РќРµС‚ РґР°РЅРЅС‹С… OHLCV РґР»СЏ {symbol}", chat_id)
            return

        df = _ohlcv_to_df(ohlcv)
        last_price = float(df["close"].iloc[-1]) if not df.empty else None
        atr_value = _atr(df, period=14)

        engine = scoring_engine.ScoringEngine()
        ai_score = 0.75
        if hasattr(engine, "evaluate"):
            scores = engine.evaluate(df, ai_score=ai_score)
        elif hasattr(engine, "calculate_scores"):
            scores = engine.calculate_scores(df, ai_score=ai_score)
        else:
            scores = (0.5, ai_score, {})

        if isinstance(scores, tuple) and len(scores) >= 2:
            buy_score, ai_score_eval = float(scores[0]), float(scores[1])
            details = scores[2] if len(scores) > 2 else {}
        else:
            buy_score, ai_score_eval = 0.5, ai_score
            details = {}

        lines = []
        signal_emoji = "рџ“€" if buy_score > 0.6 else "рџ“Љ"
        lines.append(f"{signal_emoji} Test Analysis {symbol} ({timeframe})")
        if last_price:
            lines.append(f"Р¦РµРЅР°: ${last_price:.2f}")
        lines.append(f"рџ”µ ATR: {atr_value:.4f} (UNIFIED)")
        lines.append(f"Score {buy_score:.1f} / AI {ai_score_eval:.2f}")

        if details:
            rsi = details.get("rsi")
            if rsi is not None:
                rsi_emoji = "рџџў" if 30 <= rsi <= 70 else "рџ”ґ"
                lines.append(f"{rsi_emoji} RSI: {float(rsi):.1f}")
            macd_hist = details.get("macd_hist")
            if macd_hist is not None:
                macd_emoji = "рџ“€" if macd_hist > 0 else "рџ“‰"
                lines.append(f"{macd_emoji} MACD: {float(macd_hist):.4f}")
            market_condition = details.get("market_condition")
            if market_condition:
                lines.append(f"рџЊЉ Market: {market_condition}")

        if buy_score > 0.65 and ai_score_eval > 0.70:
            lines.append("\nвњ… РЎРёРіРЅР°Р»: POTENTIAL BUY")
        elif buy_score < 0.4:
            lines.append("\nвќЊ РЎРёРіРЅР°Р»: AVOID")
        else:
            lines.append("\nвЏі РЎРёРіРЅР°Р»: WAIT")

        # Р“СЂР°С„РёРє: РјСЏРіРєРёР№ С„РѕР»Р±СЌРє, РµСЃР»Рё matplotlib РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ
        chart_path = None
        if generate_price_chart and CHARTS_READY and not df.empty:
            try:
                chart_path = generate_price_chart(df, title=f"{symbol} ({timeframe})")
            except Exception as e:
                logging.warning(f"chart generation failed: {e}")

        # РћС‚РїСЂР°РІРєР°
        send_message("\n".join(lines), chat_id)
        if chart_path:
            send_photo(chart_path, caption=f"Р“СЂР°С„РёРє {symbol} | ATR: {atr_value:.4f}", chat_id=chat_id)
            try:
                os.remove(chart_path)
            except Exception:
                pass

    except Exception as e:
        logging.exception("cmd_test error")
        send_message(f"вќЊ РћС€РёР±РєР° С‚РµСЃС‚РёСЂРѕРІР°РЅРёСЏ: {e}", chat_id)


@safe_command
def cmd_testbuy(state_manager: StateManager, exchange_client: ExchangeClient,
                amount_usd: float = None, chat_id: str = None):
    symbol = SYMBOL_ENV
    try:
        amount = float(amount_usd if amount_usd is not None else TRADE_AMOUNT)
    except (ValueError, TypeError):
        amount = TRADE_AMOUNT

    try:
        st = state_manager.state
        if st.get("in_position") or st.get("opening"):
            send_message("вЏ­пёЏ РЈР¶Рµ РµСЃС‚СЊ РѕС‚РєСЂС‹С‚Р°СЏ РїРѕР·РёС†РёСЏ РёР»Рё РїСЂРѕС†РµСЃСЃ РѕС‚РєСЂС‹С‚РёСЏ", chat_id)
            return

        ohlcv = exchange_client.get_ohlcv(symbol, timeframe=TIMEFRAME_ENV, limit=200)
        df = _ohlcv_to_df(ohlcv)
        last_price = float(df["close"].iloc[-1]) if not df.empty else None
        atr_val = _atr(df)

        # РЎРёРјСѓР»РёСЂСѓРµРј РѕС‚РєСЂС‹С‚РёРµ РїРѕР·РёС†РёРё С‡РµСЂРµР· state РЅР°РїСЂСЏРјСѓСЋ
        if last_price:
            qty = amount / last_price
            state_manager.state.update({
                "in_position": True,
                "position_side": "long",
                "entry_price": last_price,
                "entry_time": time.time(),
                "qty": qty,
                "qty_base": qty,
                "qty_usd": amount,
                "symbol": symbol,
                "paper": True,
                "sl_atr": last_price * 0.98,  # -2% СЃС‚РѕРї-Р»РѕСЃСЃ
                "tp1_atr": last_price * 1.02,  # +2% С‚РµР№Рє-РїСЂРѕС„РёС‚
                "buy_score": 1.0,
                "ai_score": 1.0
            })
            
            # РћС‚РїСЂР°РІР»СЏРµРј СѓРІРµРґРѕРјР»РµРЅРёРµ
            lines = [
                f"рџ“€ TEST BUY {symbol} @ {last_price:.2f}",
                f"РЎСѓРјРјР°: ${amount:.2f}",
                f"рџ”µ ATR: {atr_val:.4f} (UNIFIED)",
                "Mode: PAPER TRADING",
            ]
            send_message("\n".join(lines), chat_id)
        else:
            send_message("вќЊ РўРµСЃС‚РѕРІР°СЏ РїРѕРєСѓРїРєР° РЅРµ РІС‹РїРѕР»РЅРµРЅР°. РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ С†РµРЅСѓ.", chat_id)

    except Exception as e:
        logging.exception("cmd_testbuy error")
        send_message(f"вќЊ РћС€РёР±РєР° TEST BUY: {e}", chat_id)


@safe_command
def cmd_testsell(state_manager: StateManager, exchange_client: ExchangeClient, chat_id: str = None):
    symbol = SYMBOL_ENV
    try:
        st = state_manager.state
        if not st.get("in_position"):
            send_message("вЏ­пёЏ РќРµС‚ РѕС‚РєСЂС‹С‚РѕР№ РїРѕР·РёС†РёРё РґР»СЏ РїСЂРѕРґР°Р¶Рё", chat_id)
            return

        last_price = None
        try:
            ohlcv = exchange_client.get_ohlcv(symbol, timeframe=TIMEFRAME_ENV, limit=5)
            df = _ohlcv_to_df(ohlcv)
            last_price = float(df["close"].iloc[-1]) if not df.empty else None
        except Exception:
            pass

        if not last_price:
            send_message("вќЊ РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ С‚РµРєСѓС‰СѓСЋ С†РµРЅСѓ", chat_id)
            return

        entry_price = float(st.get("entry_price", 0.0))
        qty_base_stored = float(st.get("qty_base", 0.0))
        qty_usd = float(st.get("qty_usd", 0.0))

        if qty_base_stored <= 0:
            send_message("вќЊ Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё СЂР°РІРµРЅ РЅСѓР»СЋ", chat_id)
            return

        # РЎРёРјСѓР»РёСЂСѓРµРј Р·Р°РєСЂС‹С‚РёРµ РїРѕР·РёС†РёРё
        pnl_abs = (last_price - entry_price) * qty_base_stored
        pnl_pct = ((last_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        
        # РћС‡РёС‰Р°РµРј СЃРѕСЃС‚РѕСЏРЅРёРµ
        state_manager.state.update({
            "in_position": False,
            "position_side": None,
            "entry_price": 0,
            "qty": 0,
            "qty_base": 0,
            "qty_usd": 0,
            "symbol": None,
            "paper": False,
            "sl_atr": 0,
            "tp1_atr": 0,
            "buy_score": 0,
            "ai_score": 0
        })
        
        # РћС‚РїСЂР°РІР»СЏРµРј СѓРІРµРґРѕРјР»РµРЅРёРµ
        pnl_emoji = "рџџў" if pnl_pct >= 0 else "рџ”ґ"
        lines = [
            f"{pnl_emoji} TEST SELL {symbol} @ {last_price:.2f}",
            f"Entry: {entry_price:.2f}",
            f"PnL: {pnl_pct:+.2f}% (${pnl_abs:+.2f})",
            f"Size: ${qty_usd:.2f}",
        ]
        send_message("\n".join(lines), chat_id)

    except Exception as e:
        logging.exception("cmd_testsell error")
        send_message(f"вќЊ РћС€РёР±РєР° TEST SELL: {e}", chat_id)


@safe_command
def cmd_help(chat_id: str = None):
    help_text = (
        "рџ“њ РЎРїСЂР°РІРєР° РїРѕ РєРѕРјР°РЅРґР°Рј:\n\n"
        "рџ”§ РћСЃРЅРѕРІРЅС‹Рµ РєРѕРјР°РЅРґС‹:\n"
        "/start вЂ” Р—Р°РїСѓСЃРє Рё РїСЂРёРІРµС‚СЃС‚РІРёРµ\n"
        "/status вЂ” РўРµРєСѓС‰Р°СЏ РїРѕР·РёС†РёСЏ (СѓР»СѓС‡С€РµРЅРѕ)\n"
        "/profit вЂ” РЎС‚Р°С‚РёСЃС‚РёРєР° С‚РѕСЂРіРѕРІР»Рё\n"
        "/lasttrades вЂ” РџРѕСЃР»РµРґРЅРёРµ 5 СЃРґРµР»РѕРє\n\n"
        "рџ§Є РўРµСЃС‚РёСЂРѕРІР°РЅРёРµ:\n"
        "/test [СЃРёРјРІРѕР»] вЂ” РђРЅР°Р»РёР· СЂС‹РЅРєР° СЃ ATR\n"
        "/testbuy [СЃСѓРјРјР°] вЂ” РўРµСЃС‚РѕРІР°СЏ РїРѕРєСѓРїРєР°\n"
        "/testsell вЂ” РўРµСЃС‚РѕРІР°СЏ РїСЂРѕРґР°Р¶Р°\n\n"
        "рџ› пёЏ РЎР»СѓР¶РµР±РЅС‹Рµ:\n"
        "/errors вЂ” РџРѕСЃР»РµРґРЅРёРµ РѕС€РёР±РєРё\n"
        "/train вЂ” РћР±СѓС‡РёС‚СЊ AI РјРѕРґРµР»СЊ\n"
        "/help вЂ” Р­С‚Р° СЃРїСЂР°РІРєР°\n\n"
        "вњ… UNIFIED ATR СЃРёСЃС‚РµРјР° Р°РєС‚РёРІРЅР°\n"
        "в„№пёЏ РџСЂРёРјРµСЂС‹:\n"
        "вЂў /test BTC/USDT 15m\n"
        "вЂў /testbuy 10\n"
        "вЂў /status"
    )
    send_message(help_text, chat_id)


def process_command(text: str, state_manager: StateManager, exchange_client: ExchangeClient,
                    train_func: Optional[Callable] = None, chat_id: str = None):
    """Р“Р»Р°РІРЅР°СЏ С„СѓРЅРєС†РёСЏ РѕР±СЂР°Р±РѕС‚РєРё РєРѕРјР°РЅРґ РѕС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return

    parts = text.split()
    command = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []

    try:
        if command == "/start":
            cmd_start(chat_id)
        elif command == "/status":
            cmd_status(state_manager, exchange_client, chat_id)
        elif command == "/profit":
            cmd_profit(chat_id)
        elif command == "/errors":
            cmd_errors(chat_id)
        elif command == "/lasttrades":
            cmd_lasttrades(chat_id)
        elif command == "/help":
            cmd_help(chat_id)
        elif command == "/train":
            cmd_train(train_func if train_func else lambda: False, chat_id)
        elif command == "/test":
            symbol = args[0] if len(args) > 0 else None
            timeframe = args[1] if len(args) > 1 else None
            cmd_test(symbol, timeframe, chat_id)
        elif command == "/testbuy":
            amount = None
            if len(args) > 0:
                try:
                    amount = float(args[0])
                except ValueError:
                    send_message("вќЊ РќРµРІРµСЂРЅС‹Р№ С„РѕСЂРјР°С‚ СЃСѓРјРјС‹. РСЃРїРѕР»СЊР·СѓР№С‚Рµ: /testbuy 10", chat_id)
                    return
            cmd_testbuy(state_manager, exchange_client, amount, chat_id)
        elif command == "/testsell":
            cmd_testsell(state_manager, exchange_client, chat_id)
        else:
            send_message(f"вќ“ РќРµРёР·РІРµСЃС‚РЅР°СЏ РєРѕРјР°РЅРґР°: {command}\nРСЃРїРѕР»СЊР·СѓР№С‚Рµ /help РґР»СЏ СЃРїСЂР°РІРєРё", chat_id)
    except Exception as e:
        logging.exception(f"process_command error: {e}")
        send_message(f"вљ пёЏ РћС€РёР±РєР° РѕР±СЂР°Р±РѕС‚РєРё РєРѕРјР°РЅРґС‹: {e}", chat_id)

