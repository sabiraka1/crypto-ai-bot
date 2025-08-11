import os
import logging
import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import time
from typing import Optional, Callable, List

from analysis import scoring_engine
from trading.exchange_client import ExchangeClient
from core.state_manager import StateManager
from utils.csv_handler import CSVHandler
from config.settings import TradingConfig

# ── Конфигурация ──────────────────────────────────────────────────────────────
CFG = TradingConfig()

# ==== API ====
BOT_TOKEN = CFG.BOT_TOKEN
CHAT_ID = CFG.CHAT_ID
ADMIN_CHAT_IDS = CFG.ADMIN_CHAT_IDS
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

SYMBOL_ENV = CFG.SYMBOL
TIMEFRAME_ENV = CFG.TIMEFRAME
TEST_TRADE_AMOUNT = CFG.TEST_TRADE_AMOUNT

# ==== Anti-spam settings ====
_last_command_time = {}
COMMAND_COOLDOWN = CFG.COMMAND_COOLDOWN


def anti_spam(user_id):
    """Проверка на спам команд"""
    now = time.time()
    if user_id in _last_command_time and now - _last_command_time[user_id] < COMMAND_COOLDOWN:
        return False
    _last_command_time[user_id] = now
    return True


def is_authorized(chat_id: str) -> bool:
    """Проверка авторизации пользователя"""
    if not ADMIN_CHAT_IDS:
        return True  # Если список админов пуст, разрешаем всем
    return str(chat_id) in ADMIN_CHAT_IDS


def safe_command(func):
    """Декоратор: защита команд от ошибок, антиспам и авторизация"""
    def wrapper(*args, **kwargs):
        # Попытка извлечь chat_id из аргументов
        chat_id = None
        try:
            # Предполагаем что первый аргумент может содержать chat_id
            if args and isinstance(args[0], dict):
                chat_id = args[0].get("message", {}).get("chat", {}).get("id")
            elif len(args) > 1 and isinstance(args[1], (str, int)):
                chat_id = str(args[1])
                
        except Exception:
            pass
            
        # Проверка авторизации
        if chat_id and not is_authorized(chat_id):
            logging.warning(f"❌ Unauthorized access attempt from chat_id: {chat_id}")
            send_message("❌ У вас нет прав для выполнения команд.", chat_id=str(chat_id))
            return
            
        # Проверка антиспама
        if chat_id and not anti_spam(chat_id):
            send_message("⏳ Подожди пару секунд перед следующей командой.", chat_id=str(chat_id))
            return
            
        # Выполнение команды
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.exception(f"Ошибка в команде {func.__name__}: {e}")
            if chat_id:
                send_message("⚠️ Произошла ошибка при выполнении команды.", chat_id=str(chat_id))
                
    return wrapper


# ==== Telegram helpers ====
def _tg_request(method: str, data: dict, files: Optional[dict] = None) -> None:
    """Базовый запрос к Telegram API"""
    if not TELEGRAM_API:
        logging.warning("Telegram not configured (BOT_TOKEN missing)")
        return
        
    url = f"{TELEGRAM_API}/{method}"
    try:
        resp = requests.post(url, data=data, files=files, timeout=15)
        if resp.status_code != 200:
            logging.error("Telegram API error: %s %s", resp.status_code, resp.text[:200])
        else:
            logging.debug("[TG] %s ok", method)
    except Exception as e:
        logging.exception("Telegram request failed: %s", e)


def send_message(text: str, chat_id: str = None) -> None:
    """Отправка сообщения в Telegram"""
    target_chat = chat_id or CHAT_ID
    if target_chat:
        _tg_request("sendMessage", {"chat_id": target_chat, "text": text})


def send_photo(image_path: str, caption: Optional[str] = None, chat_id: str = None) -> None:
    """Отправка фото в Telegram"""
    target_chat = chat_id or CHAT_ID
    if not target_chat:
        return
        
    if not os.path.exists(image_path):
        logging.warning("send_photo: file not found: %s", image_path)
        return
        
    with open(image_path, "rb") as f:
        files = {"photo": f}
        data = {"chat_id": target_chat}
        if caption:
            data["caption"] = caption
        _tg_request("sendPhoto", data, files=files)


# ==== Commands ====
@safe_command
def cmd_start(chat_id: str = None) -> None:
    """Команда /start"""
    message = (
        "🚀 Торговый бот запущен!\n\n"
        "📋 Доступные команды:\n"
        "/status – Показать открытую позицию\n"
        "/profit – Общий PnL и Winrate\n"
        "/lasttrades – Последние сделки\n"
        "/test – Тест сигнала\n"
        "/testbuy [сумма] – Тестовая покупка\n"
        "/testsell – Тестовая продажа\n"
        "/help – Справка по командам\n"
        "/errors – Последние ошибки\n"
        "/train – Обучить AI модель"
    )
    send_message(message, chat_id)


@safe_command
def cmd_status(state_manager: StateManager, exchange_client: ExchangeClient, chat_id: str = None) -> None:
    """Команда /status - показать текущую позицию"""
    try:
        st = getattr(state_manager, "state", {}) or {}
        
        if not st.get("in_position"):
            send_message("🟢 Позиции нет", chat_id)
            return
            
        sym = st.get("symbol", SYMBOL_ENV)
        entry = float(st.get("entry_price") or 0.0)
        
        # Получаем текущую цену
        try:
            current_price = exchange_client.get_last_price(sym)
        except Exception as e:
            logging.error(f"Failed to get current price: {e}")
            current_price = None

        txt = [f"📌 Позиция LONG {sym} @ {entry:.6f}"]
        
        if current_price:
            pnl_pct = (current_price - entry) / entry * 100.0 if entry else 0.0
            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
            txt.append(f"Текущая цена: {current_price:.6f}")
            txt.append(f"{pnl_emoji} PnL: {pnl_pct:+.2f}%")

        # Информация о TP/SL
        tp = st.get("tp1_atr")
        sl = st.get("sl_atr")
        if tp and sl:
            txt.append(f"🎯 TP: {float(tp):.6f} | 🛡️ SL: {float(sl):.6f}")

        # Дополнительная информация
        flags = []
        if st.get("partial_taken"):
            flags.append("Частичное TP")
        if st.get("trailing_on"):
            flags.append("Трейлинг ON")
            
        qty_usd = st.get("qty_usd")
        if qty_usd:
            flags.append(f"${float(qty_usd):.2f}")
            
        if flags:
            txt.append("ℹ️ " + " | ".join(flags))

        send_message("\n".join(txt), chat_id)
        
    except Exception as e:
        logging.exception("cmd_status error")
        send_message(f"⚠️ Ошибка при получении статуса: {e}", chat_id)


# telegram/bot_handler.py - исправленные функции

@safe_command
def cmd_profit(chat_id: str = None) -> None:
    """Команда /profit - показать общую статистику"""
    try:
        path = CFG.CLOSED_TRADES_CSV
        if not os.path.exists(path):
            send_message("📊 PnL: 0.00 USDT\nWinrate: 0.0%\nТрейдов: 0", chat_id)
            return
            
        # ИСПРАВЛЕНИЕ: CSVHandler.read_csv_safe возвращает list, не DataFrame
        trades_list = CSVHandler.read_csv_safe(path)
        if not trades_list:  # проверяем пустой list
            send_message("📊 PnL: 0.00 USDT\nWinrate: 0.0%\nТрейдов: 0", chat_id)
            return
            
        # Конвертируем list в DataFrame
        df = pd.DataFrame(trades_list)
        if df.empty:
            send_message("📊 PnL: 0.00 USDT\nWinrate: 0.0%\nТрейдов: 0", chat_id)
            return
            
        # Приведение типов с обработкой ошибок
        if "pnl_abs" in df.columns:
            df["pnl_abs"] = pd.to_numeric(df["pnl_abs"], errors="coerce").fillna(0.0)
        else:
            df["pnl_abs"] = 0.0
            
        if "pnl_pct" in df.columns:
            df["pnl_pct"] = pd.to_numeric(df["pnl_pct"], errors="coerce").fillna(0.0)
        else:
            df["pnl_pct"] = 0.0

        # Расчеты с безопасными значениями
        total_pnl = float(df["pnl_abs"].sum())
        wins = int((df["pnl_pct"] > 0).sum())
        total_trades = int(len(df))
        win_rate = (wins / total_trades * 100.0) if total_trades else 0.0
        
        # Дополнительная статистика
        if total_trades > 0:
            avg_win = df[df["pnl_pct"] > 0]["pnl_pct"].mean() if wins > 0 else 0.0
            avg_loss = df[df["pnl_pct"] < 0]["pnl_pct"].mean() if (total_trades - wins) > 0 else 0.0
            
            # Обработка NaN значений
            avg_win = avg_win if pd.notna(avg_win) else 0.0
            avg_loss = avg_loss if pd.notna(avg_loss) else 0.0
            
            message = (
                f"📊 Торговая статистика:\n"
                f"💰 Общий PnL: {total_pnl:.2f} USDT\n"
                f"📈 Winrate: {win_rate:.1f}% ({wins}/{total_trades})\n"
                f"🟢 Средний профит: {avg_win:.2f}%\n"
                f"🔴 Средний убыток: {avg_loss:.2f}%\n"
                f"📊 Всего сделок: {total_trades}"
            )
        else:
            message = "📊 Статистика недоступна - нет завершенных сделок"
            
        send_message(message, chat_id)
        
    except Exception as e:
        logging.exception("cmd_profit error")
        send_message(f"⚠️ Ошибка при расчете статистики: {e}", chat_id)


@safe_command
def cmd_lasttrades(chat_id: str = None) -> None:
    """Команда /lasttrades - показать последние сделки"""
    try:
        # Используем правильный метод из CSVHandler
        trades = CSVHandler.read_last_trades(limit=5)
        if not trades:
            send_message("📋 Сделок ещё нет", chat_id)
            return
            
        lines: List[str] = ["📋 Последние сделки:"]
        
        for i, trade in enumerate(trades, 1):
            side = str(trade.get("side", "LONG"))
            entry = trade.get("entry_price", "")
            exit_price = trade.get("exit_price", "")
            pnl_pct = trade.get("pnl_pct", "")
            reason = str(trade.get("reason", ""))
            
            # Форматируем строку сделки
            trade_line = f"{i}. {side}"
            
            if entry and exit_price:
                try:
                    trade_line += f" {float(entry):.2f}→{float(exit_price):.2f}"
                except (ValueError, TypeError):
                    trade_line += f" {entry}→{exit_price}"
                    
            if pnl_pct:
                try:
                    pnl_val = float(pnl_pct)
                    emoji = "🟢" if pnl_val >= 0 else "🔴"
                    trade_line += f" {emoji}{pnl_val:+.2f}%"
                except (ValueError, TypeError):
                    trade_line += f" {pnl_pct}%"
                    
            if reason:
                trade_line += f" ({reason})"
                
            lines.append(trade_line)
            
        send_message("\n".join(lines), chat_id)
        
    except Exception as e:
        logging.exception("cmd_lasttrades error")
        send_message(f"⚠️ Ошибка при получении сделок: {e}", chat_id)


@safe_command
def cmd_errors(chat_id: str = None) -> None:
    """Команда /errors - показать последние ошибки"""
    log_path = "bot_activity.log"
    if not os.path.exists(log_path):
        send_message("📝 Лог-файл ещё не создан", chat_id)
        return
        
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        # Ищем последние строки с ERROR или WARNING
        error_lines = []
        for line in reversed(lines[-100:]):  # последние 100 строк
            if any(level in line for level in ["ERROR", "WARNING", "EXCEPTION"]):
                error_lines.append(line.strip())
                if len(error_lines) >= 10:  # максимум 10 ошибок
                    break
                    
        if error_lines:
            message = "🚨 Последние ошибки:\n" + "\n".join(reversed(error_lines))
            # Обрезаем если слишком длинное
            if len(message) > 4000:
                message = message[:4000] + "..."
        else:
            message = "✅ Ошибок в последних логах не найдено"
            
        send_message(message, chat_id)
        
    except Exception as e:
        send_message(f"⚠️ Ошибка чтения лога: {e}", chat_id)


@safe_command
def cmd_lasttrades(chat_id: str = None) -> None:
    """Команда /lasttrades - показать последние сделки"""
    try:
        trades = CSVHandler.read_last_trades(limit=5)
        if not trades:
            send_message("📋 Сделок ещё нет", chat_id)
            return
            
        lines: List[str] = ["📋 Последние сделки:"]
        
        for i, trade in enumerate(trades, 1):
            side = str(trade.get("side", "LONG"))
            entry = trade.get("entry_price", "")
            exit_price = trade.get("exit_price", "")
            pnl_pct = trade.get("pnl_pct", "")
            reason = str(trade.get("reason", ""))
            
            # Форматируем строку сделки
            trade_line = f"{i}. {side}"
            
            if entry and exit_price:
                try:
                    trade_line += f" {float(entry):.2f}→{float(exit_price):.2f}"
                except:
                    trade_line += f" {entry}→{exit_price}"
                    
            if pnl_pct:
                try:
                    pnl_val = float(pnl_pct)
                    emoji = "🟢" if pnl_val >= 0 else "🔴"
                    trade_line += f" {emoji}{pnl_val:+.2f}%"
                except:
                    trade_line += f" {pnl_pct}%"
                    
            if reason:
                trade_line += f" ({reason})"
                
            lines.append(trade_line)
            
        send_message("\n".join(lines), chat_id)
        
    except Exception as e:
        logging.exception("cmd_lasttrades error")
        send_message(f"⚠️ Ошибка при получении сделок: {e}", chat_id)


@safe_command
def cmd_train(train_func: Callable, chat_id: str = None) -> None:
    """Команда /train - обучение AI модели"""
    send_message("🧠 Запуск обучения AI модели...", chat_id)
    
    try:
        if not train_func:
            send_message("❌ Функция обучения недоступна", chat_id)
            return
            
        success = train_func()
        
        if success:
            send_message("✅ AI модель успешно обучена!", chat_id)
        else:
            send_message("❌ Ошибка при обучении модели", chat_id)
            
    except Exception as e:
        logging.exception("cmd_train error")
        send_message(f"❌ Ошибка обучения: {e}", chat_id)


# ==== Helpers ====
def _ohlcv_to_df(ohlcv) -> pd.DataFrame:
    """Конвертация OHLCV в DataFrame"""
    if not ohlcv:
        return pd.DataFrame()
        
    cols = ["time", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(ohlcv, columns=cols)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.set_index("time", inplace=True)
    return df


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    """✅ UNIFIED: ATR для telegram команд"""
    try:
        from analysis.technical_indicators import _atr_for_telegram
        return _atr_for_telegram(df, period)
    except Exception as e:
        logging.error(f"Telegram ATR failed: {e}")
        # Простой fallback
        return float((df["high"] - df["low"]).mean()) if not df.empty else 0.0


# ==== Test commands ====
@safe_command
def cmd_test(symbol: str = None, timeframe: str = None, chat_id: str = None):
    """Команда /test - тестирование анализа рынка"""
    symbol = symbol or SYMBOL_ENV
    timeframe = timeframe or TIMEFRAME_ENV
    
    try:
        # Создаем временный exchange client
        ex = ExchangeClient(safe_mode=True)  # Всегда безопасный режим для тестов
        
        # Получаем данные
        ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=200)
        if not ohlcv:
            send_message(f"⚠️ Нет данных OHLCV для {symbol}", chat_id)
            return
            
        df = _ohlcv_to_df(ohlcv)
        
        # Анализируем сигнал
        engine = scoring_engine.ScoringEngine()
        
        # Используем правильный метод
        if hasattr(engine, "evaluate"):
            scores = engine.evaluate(df, ai_score=0.55)
        elif hasattr(engine, "calculate_scores"):
            scores = engine.calculate_scores(df, ai_score=0.55)
        else:
            scores = (0.5, 0.55, {})
            
        if isinstance(scores, tuple) and len(scores) >= 2:
            buy_score, ai_score = float(scores[0]), float(scores[1])
            details = scores[2] if len(scores) > 2 else {}
        else:
            buy_score, ai_score = 0.5, 0.55
            details = {}
        
        # Получаем последнюю цену
        last_price = ex.get_last_price(symbol)
        
        # Формируем отчет
        message = [
            f"🧪 TEST анализ {symbol} ({timeframe})",
            f"💰 Цена: {last_price:.2f}",
            f"📊 Buy Score: {buy_score:.2f}",
            f"🤖 AI Score: {ai_score:.2f}",
            ""
        ]
        
        # Добавляем детали если есть
        if details:
            rsi = details.get("rsi")
            if rsi:
                message.append(f"📈 RSI: {rsi:.1f}")
                
            macd_hist = details.get("macd_hist")
            if macd_hist is not None:
                message.append(f"📊 MACD Hist: {macd_hist:.4f}")
                
            market_condition = details.get("market_condition")
            if market_condition:
                message.append(f"🌊 Market: {market_condition}")
        
        # Создаем простой график
        try:
            plt.figure(figsize=(10, 6))
            df["close"].plot(title=f"{symbol} Price Chart", color='blue')
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            
            chart_path = "test_chart.png"
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close()
            
            # Отправляем сообщение и график
            send_message("\n".join(message), chat_id)
            send_photo(chart_path, caption=f"График {symbol}", chat_id=chat_id)
            
            # Удаляем временный файл
            try:
                os.remove(chart_path)
            except:
                pass
                
        except Exception as e:
            logging.error(f"Chart creation failed: {e}")
            send_message("\n".join(message), chat_id)
            
    except Exception as e:
        logging.exception("cmd_test error")
        send_message(f"❌ Ошибка тестирования: {e}", chat_id)


@safe_command
def cmd_testbuy(state_manager: StateManager, exchange_client: ExchangeClient, 
                amount_usd: float = None, chat_id: str = None):
    """Команда /testbuy - тестовая покупка"""
    symbol = SYMBOL_ENV
    
    try:
        amount = float(amount_usd if amount_usd is not None else TEST_TRADE_AMOUNT)
    except (ValueError, TypeError):
        amount = TEST_TRADE_AMOUNT

    try:
        # Проверяем, что нет открытой позиции
        st = state_manager.state
        if st.get("in_position") or st.get("opening"):
            send_message("⏭️ Уже есть открытая позиция или процесс открытия", chat_id)
            return

        # Получаем данные рынка
        ohlcv = exchange_client.fetch_ohlcv(symbol, timeframe=TIMEFRAME_ENV, limit=200)
        df = _ohlcv_to_df(ohlcv)
        last_price = float(df["close"].iloc[-1]) if not df.empty else exchange_client.get_last_price(symbol)
        atr_val = _atr(df)

        # Создаем временный PositionManager для тестовой покупки
        def test_notify_entry(*args, **kwargs):
            send_message(f"🧪 TEST BUY уведомление: позиция открыта", chat_id)
        
        def test_notify_close(*args, **kwargs):
            send_message(f"🧪 TEST позиция закрыта", chat_id)

        from trading.position_manager import SimplePositionManager
        pm = SimplePositionManager(
            exchange_client, 
            state_manager, 
            notify_entry_func=test_notify_entry, 
            notify_close_func=test_notify_close
        )
        
        # Принудительно открываем позицию в безопасном режиме
        result = pm.open_long(
            symbol=symbol, 
            amount_usd=amount, 
            entry_price=last_price, 
            atr=atr_val or 0.0,
            buy_score=1.0,  # Фиксированные значения для теста
            ai_score=1.0, 
            amount_frac=1.0,
            market_condition="test",
            pattern="test_pattern"
        )
        
        if result is None:
            send_message("❌ Тестовая покупка не выполнена. Проверьте логи.", chat_id)
        else:
            min_cost = exchange_client.market_min_cost(symbol) or 0.0
            actual_amount = max(amount, min_cost)
            
            message = [
                f"✅ TEST BUY выполнен",
                f"💰 Символ: {symbol}",
                f"💵 Запрошено: ${amount:.2f}",
                f"💵 Выполнено: ${actual_amount:.2f}",
                f"📈 Цена: {last_price:.6f}",
                f"🔧 Режим: {'paper' if result.get('paper') else 'real'}",
                f"🆔 ID: {result.get('id', 'N/A')}"
            ]
            
            send_message("\n".join(message), chat_id)
            
    except Exception as e:
        logging.exception("cmd_testbuy error")
        send_message(f"❌ Ошибка TEST BUY: {e}", chat_id)


@safe_command
def cmd_testsell(state_manager: StateManager, exchange_client: ExchangeClient, chat_id: str = None):
    """Команда /testsell - тестовая продажа"""
    symbol = SYMBOL_ENV
    
    try:
        # Проверяем есть ли позиция
        st = state_manager.state
        if not st.get("in_position"):
            send_message("⏭️ Нет открытой позиции для продажи", chat_id)
            return

        # Получаем текущую цену
        last_price = exchange_client.get_last_price(symbol)
        if not last_price or last_price <= 0:
            send_message("❌ Не удалось получить текущую цену", chat_id)
            return

        # Получаем данные позиции
        entry_price = float(st.get("entry_price", 0.0))
        qty_base_stored = float(st.get("qty_base", 0.0))
        qty_usd = float(st.get("qty_usd", 0.0))
        
        if qty_base_stored <= 0:
            send_message("❌ Размер позиции равен нулю", chat_id)
            return

        # Создаем PositionManager для продажи
        def test_notify_close(*args, **kwargs):
            send_message(f"🧪 TEST SELL завершен", chat_id)

        from trading.position_manager import SimplePositionManager
        pm = SimplePositionManager(
            exchange_client, 
            state_manager, 
            notify_entry_func=None, 
            notify_close_func=test_notify_close
        )
        
        # Закрываем позицию
        result = pm.close_all(symbol, exit_price=last_price, reason="manual_test_sell")
        
        if result is None:
            send_message("❌ Тестовая продажа не выполнена", chat_id)
        else:
            # Рассчитываем PnL
            pnl_pct = (last_price - entry_price) / entry_price * 100.0 if entry_price > 0 else 0.0
            pnl_abs = (last_price - entry_price) * qty_base_stored if entry_price > 0 else 0.0
            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
            
            message = [
                f"✅ TEST SELL выполнен",
                f"💰 Символ: {symbol}",
                f"📊 Продано: {qty_base_stored:.8f}",
                f"📈 Цена продажи: {last_price:.6f}",
                f"📉 Цена покупки: {entry_price:.6f}",
                f"{pnl_emoji} PnL: {pnl_pct:+.2f}% ({pnl_abs:+.2f} USDT)",
                f"💵 Размер позиции: ${qty_usd:.2f}"
            ]
            
            send_message("\n".join(message), chat_id)
            
    except Exception as e:
        logging.exception("cmd_testsell error")
        send_message(f"❌ Ошибка TEST SELL: {e}", chat_id)


@safe_command
def cmd_help(chat_id: str = None):
    """Команда /help - справка"""
    help_text = (
        "📜 Справка по командам:\n\n"
        "🔧 Основные команды:\n"
        "/start — Запуск и приветствие\n"
        "/status — Текущая позиция\n"
        "/profit — Статистика торговли\n"
        "/lasttrades — Последние 5 сделок\n\n"
        "🧪 Тестирование:\n"
        "/test [символ] — Анализ рынка\n"
        "/testbuy [сумма] — Тестовая покупка\n"
        "/testsell — Тестовая продажа\n\n"
        "🛠️ Служебные:\n"
        "/errors — Последние ошибки\n"
        "/train — Обучить AI модель\n"
        "/help — Эта справка\n\n"
        "ℹ️ Примеры:\n"
        "• /test BTC/USDT 15m\n"
        "• /testbuy 10\n"
        "• /status"
    )
    send_message(help_text, chat_id)


# ==== Router - главная функция обработки команд ====
def process_command(text: str, state_manager: StateManager, exchange_client: ExchangeClient, 
                   train_func: Optional[Callable] = None, chat_id: str = None):
    """
    Главная функция обработки команд от пользователя.
    
    Args:
        text: Текст команды
        state_manager: Менеджер состояния
        exchange_client: Клиент биржи
        train_func: Функция обучения AI (опционально)
        chat_id: ID чата для ответа
    """
    
    text = (text or "").strip()
    if not text.startswith("/"):
        return
    
    # Извлекаем команду и аргументы
    parts = text.split()
    command = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []
    
    try:
        # Базовые команды
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
            
        # Тестовые команды
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
                    send_message("❌ Неверный формат суммы. Используйте: /testbuy 10", chat_id)
                    return
            cmd_testbuy(state_manager, exchange_client, amount, chat_id)
            
        elif command == "/testsell":
            cmd_testsell(state_manager, exchange_client, chat_id)
            
        else:
            send_message(f"❓ Неизвестная команда: {command}\nИспользуйте /help для справки", chat_id)
            
    except Exception as e:
        logging.exception(f"process_command error: {e}")
        send_message(f"⚠️ Ошибка обработки команды: {e}", chat_id)