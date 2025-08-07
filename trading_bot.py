import os, json, logging
import ccxt
from datetime import datetime
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal, should_trade
from technical_analysis import generate_signal
from data_logger import log_real_trade, log_closed_trade, get_recent_performance
from telegram_bot import bot
from train_model import retrain_model

load_dotenv()

CHAT_ID = os.getenv("CHAT_ID")
TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", 50))
PROFIT_TARGET = 0.015  # 1.5% прибыль
STOP_LOSS = -0.02      # -2% стоп-лосс  
MAX_HOLD_MINUTES = 240  # 4 часа максимум
POSITION_FILE = "open_position.json"
RSI_MEMORY_FILE = "rsi_memory.json"

logger = logging.getLogger(__name__)

# Настройка Gate.io
exchange = ccxt.gateio({
    'apiKey': os.getenv("GATE_API_KEY"),
    'secret': os.getenv("GATE_API_SECRET"),
    'enableRateLimit': True,
    'sandbox': False  # Для реального торгования
})

def send_telegram_message(chat_id, text):
    """Отправка сообщения в Telegram с обработкой ошибок"""
    try:
        bot.send_message(chat_id, text, parse_mode='HTML')
        logger.info(f"Telegram сообщение отправлено: {text[:50]}...")
    except Exception as e:
        logger.error(f"Ошибка Telegram: {e}")

def get_open_position():
    """Получение текущей открытой позиции"""
    if os.path.exists(POSITION_FILE):
        try:
            with open(POSITION_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения позиции: {e}")
    return None

def save_position(data):
    """Сохранение позиции"""
    try:
        with open(POSITION_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Позиция сохранена: {data['type']} @ {data['entry_price']}")
    except Exception as e:
        logger.error(f"Ошибка сохранения позиции: {e}")

def clear_position():
    """Очистка файла позиции"""
    if os.path.exists(POSITION_FILE):
        try:
            os.remove(POSITION_FILE)
            logger.info("Позиция очищена")
        except Exception as e:
            logger.error(f"Ошибка очистки позиции: {e}")

def update_rsi_memory(rsi):
    """Обновление памяти RSI для анализа тенденций"""
    memory = []
    if os.path.exists(RSI_MEMORY_FILE):
        try:
            with open(RSI_MEMORY_FILE, 'r') as f:
                memory = json.load(f)
        except:
            memory = []
    
    memory.append(rsi)
    memory = memory[-10:]  # Храним последние 10 значений
    
    try:
        with open(RSI_MEMORY_FILE, 'w') as f:
            json.dump(memory, f)
    except Exception as e:
        logger.error(f"Ошибка сохранения RSI памяти: {e}")

def analyze_rsi_trend():
    """Анализ тренда RSI"""
    if not os.path.exists(RSI_MEMORY_FILE):
        return "UNKNOWN"
    
    try:
        with open(RSI_MEMORY_FILE, 'r') as f:
            memory = json.load(f)
        
        if len(memory) < 3:
            return "INSUFFICIENT_DATA"
        
        # Анализируем последние 3 значения
        recent = memory[-3:]
        
        if all(r > 75 for r in recent):
            return "EXTREMELY_OVERBOUGHT"
        elif all(r < 25 for r in recent):
            return "EXTREMELY_OVERSOLD"
        elif all(recent[i] > recent[i-1] for i in range(1, len(recent))):
            return "RISING"
        elif all(recent[i] < recent[i-1] for i in range(1, len(recent))):
            return "FALLING"
        else:
            return "SIDEWAYS"
            
    except Exception as e:
        logger.error(f"Ошибка анализа RSI тренда: {e}")
        return "ERROR"

def close_position(position, reason, current_result=None):
    """Закрытие позиции с полным логированием"""
    symbol = position['symbol']
    side = 'sell' if position['type'] == 'buy' else 'buy'
    
    try:
        # Получаем текущую цену
        ticker = exchange.fetch_ticker(symbol)
        price_now = ticker['last']
        amount = position['amount']
        entry_price = position['entry_price']
        
        # Имитация закрытия позиции (закомментируйте для реального торгования)
        # order = exchange.create_order(symbol, 'market', side, amount)
        logger.info(f"Позиция закрыта: {side} {amount} {symbol} @ {price_now}")
        
        # Расчет прибыли/убытка
        if position['type'] == 'buy':
            profit = (price_now - entry_price) / entry_price
        else:
            profit = (entry_price - price_now) / entry_price
        
        # Логирование закрытой сделки
        log_closed_trade(
            entry_price=entry_price,
            close_price=price_now,
            pnl_percent=profit,
            reason=reason,
            signal=position.get('original_signal', position['type'].upper()),
            score=position.get('ai_score', 0),
            result_data=current_result
        )
        
        # Формирование сообщения
        profit_emoji = "🟢" if profit > 0 else "🔴"
        message = (
            f"{profit_emoji} <b>Сделка закрыта</b>\n"
            f"📊 {position['type'].upper()}: {entry_price:.2f} → {price_now:.2f}\n"
            f"💰 P&L: <b>{profit*100:+.2f}%</b>\n"
            f"⏰ Причина: {reason}\n"
            f"🕐 Время удержания: {position.get('hold_time', 'N/A')}"
        )
        
        # Добавляем информацию о текущих условиях
        if current_result:
            message += f"\n📈 RSI: {current_result.get('rsi', 0):.1f} | Pattern: {current_result.get('pattern', 'NONE')}"
        
        send_telegram_message(CHAT_ID, message)
        
        # Переобучение модели после каждой закрытой сделки
        try:
            retrain_model()
            logger.info("✅ Модель переобучена после закрытия сделки")
        except Exception as e:
            logger.error(f"Ошибка переобучения модели: {e}")
        
        clear_position()
        return True
        
    except Exception as e:
        logger.error(f"Ошибка закрытия сделки: {e}")
        send_telegram_message(CHAT_ID, f"❌ Ошибка закрытия сделки: {e}")
        return False

def check_close_conditions(result_data):
    """Проверка условий закрытия позиции"""
    position = get_open_position()
    if not position:
        return
    
    try:
        symbol = position['symbol']
        ticker = exchange.fetch_ticker(symbol)
        price_now = ticker['last']
        entry_price = position['entry_price']
        entry_time = datetime.fromisoformat(position['timestamp'])
        
        # Время удержания
        held_minutes = (datetime.utcnow() - entry_time).total_seconds() / 60
        position['hold_time'] = f"{int(held_minutes)} мин"
        
        # Расчет текущей прибыли
        if position['type'] == 'buy':
            current_profit = (price_now - entry_price) / entry_price
        else:
            current_profit = (entry_price - price_now) / entry_price
        
        rsi = result_data.get("rsi", 50)
        rsi_trend = analyze_rsi_trend()
        
        # Обновляем память RSI
        update_rsi_memory(rsi)
        
        # Условия закрытия
        if current_profit >= PROFIT_TARGET:
            close_position(position, f"🎯 Take Profit ({current_profit*100:.1f}%)", result_data)
            
        elif current_profit <= STOP_LOSS:
            close_position(position, f"🛑 Stop Loss ({current_profit*100:.1f}%)", result_data)
            
        elif held_minutes > MAX_HOLD_MINUTES:
            close_position(position, f"⏰ Timeout ({held_minutes:.0f} мин)", result_data)
            
        elif rsi_trend == "EXTREMELY_OVERBOUGHT" and position['type'] == 'buy':
            close_position(position, f"📈 RSI критически высок ({rsi:.1f})", result_data)
            
        elif rsi_trend == "EXTREMELY_OVERSOLD" and position['type'] == 'sell':
            close_position(position, f"📉 RSI критически низок ({rsi:.1f})", result_data)
            
    except Exception as e:
        logger.error(f"Ошибка проверки условий закрытия: {e}")

def open_position(signal, result_data, score):
    """Открытие новой позиции"""
    symbol = "BTC/USDT"
    
    try:
        ticker = exchange.fetch_ticker(symbol)
        price = ticker['last']
        amount = round(TRADE_AMOUNT / price, 6)
        side = 'buy' if signal in ['BUY', 'STRONG_BUY'] else 'sell'
        
        # Имитация открытия позиции (закомментируйте для реального торгования)
        # order = exchange.create_order(symbol, 'market', side, amount)
        logger.info(f"Позиция открыта: {side} {amount} {symbol} @ {price}")
        
        # Сохранение данных позиции
        position_data = {
            "symbol": symbol,
            "type": side,
            "entry_price": price,
            "amount": amount,
            "timestamp": datetime.utcnow().isoformat(),
            "original_signal": signal,
            "ai_score": score,
            "rsi": result_data.get("rsi"),
            "macd": result_data.get("macd"),
            "pattern": result_data.get("pattern"),
            "confidence": result_data.get("confidence")
        }
        
        save_position(position_data)
        
        # Логирование реальной сделки
        log_real_trade(signal, score, price, result_data)
        
        # Очистка памяти RSI при новой позиции
        if os.path.exists(RSI_MEMORY_FILE):
            os.remove(RSI_MEMORY_FILE)
        
        return True, price
        
    except Exception as e:
        logger.error(f"Ошибка открытия позиции: {e}")
        send_telegram_message(CHAT_ID, f"❌ Ошибка открытия ордера: {e}")
        return False, 0

def format_signal_message(result_data, score):
    """Форматирование сообщения о сигнале"""
    signal = result_data.get("signal", "NONE")
    confidence = result_data.get("confidence", 0)
    price = result_data.get("price", 0)
    rsi = result_data.get("rsi", 0)
    pattern = result_data.get("pattern", "NONE")
    pattern_score = result_data.get("pattern_score", 0)
    
    # Эмодзи для сигналов
    signal_emoji = {
        "STRONG_BUY": "🚀", "BUY": "📈",
        "STRONG_SELL": "💥", "SELL": "📉",
        "HOLD": "⏸️", "ERROR": "❌"
    }
    
    emoji = signal_emoji.get(signal, "❓")
    
    message = (
        f"{emoji} <b>{signal}</b> @ {price:.2f}\n"
        f"🤖 AI Score: <b>{score:.3f}</b>\n"
        f"🎯 Confidence: {confidence:.1f}%\n"
        f"📊 RSI: {rsi:.1f}\n"
        f"🕯️ Pattern: {pattern} ({pattern_score:.1f})"
    )
    
    return message

def check_and_trade():
    """Основная функция проверки и торговли"""
    try:
        logger.info("🔄 Запуск check_and_trade()")
        
        # Генерация сигнала
        result_data = generate_signal()
        signal = result_data.get("signal", "ERROR")
        
        if signal == "ERROR":
            logger.error("❌ Ошибка генерации сигнала")
            send_telegram_message(CHAT_ID, "❌ Ошибка генерации сигнала")
            return
        
        # Оценка сигнала
        score = evaluate_signal(result_data)
        
        # Проверка условий закрытия существующих позиций
        check_close_conditions(result_data)
        
        # Отправка информации о сигнале
        signal_message = format_signal_message(result_data, score)
        
        # Проверка, стоит ли торговать
        current_position = get_open_position()
        
        if should_trade(signal, score):
            if current_position:
                signal_message += "\n⚠️ <i>Позиция уже открыта</i>"
                send_telegram_message(CHAT_ID, signal_message)
            else:
                # Открываем новую позицию
                success, entry_price = open_position(signal, result_data, score)
                
                if success:
                    signal_message += f"\n✅ <b>Позиция открыта!</b>"
                    send_telegram_message(CHAT_ID, signal_message)
                    
                    # Получаем статистику производительности
                    perf = get_recent_performance()
                    if perf:
                        perf_msg = (
                            f"📊 <b>Статистика (последние 20 сделок):</b>\n"
                            f"🎯 Win Rate: {perf['win_rate']}%\n"
                            f"💰 Средняя прибыль: {perf['avg_profit']:.2f}%\n"
                            f"📈 Общая прибыль: {perf['total_profit']:.2f}%"
                        )
                        send_telegram_message(CHAT_ID, perf_msg)
                else:
                    signal_message += "\n❌ <i>Ошибка открытия позиции</i>"
                    send_telegram_message(CHAT_ID, signal_message)
        else:
            # Сигнал недостаточно сильный
            if score < 0.3:
                signal_message += f"\n🔸 <i>Слабый сигнал (порог: 0.65)</i>"
            else:
                signal_message += f"\n🔸 <i>Сигнал ниже порога (порог: 0.65)</i>"
            
            # Отправляем только если есть открытая позиция или интересный паттерн
            if current_position or result_data.get("pattern_score", 0) >= 4:
                send_telegram_message(CHAT_ID, signal_message)
        
        logger.info(f"✅ Цикл завершен: {signal} | Score: {score:.3f}")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_and_trade: {e}")
        send_telegram_message(CHAT_ID, f"❌ Критическая ошибка: {e}")

def get_position_summary():
    """Получение краткой сводки по позиции"""
    position = get_open_position()
    if not position:
        return "📭 Открытых позиций нет"
    
    try:
        symbol = position['symbol']
        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        entry_price = position['entry_price']
        entry_time = datetime.fromisoformat(position['timestamp'])
        
        # Время удержания
        held_minutes = (datetime.utcnow() - entry_time).total_seconds() / 60
        held_hours = held_minutes / 60
        
        # Текущая прибыль
        if position['type'] == 'buy':
            current_profit = (current_price - entry_price) / entry_price
        else:
            current_profit = (entry_price - current_price) / entry_price
        
        profit_emoji = "🟢" if current_profit > 0 else "🔴"
        
        summary = (
            f"📌 <b>Открытая позиция:</b>\n"
            f"🔄 {position['type'].upper()}: {entry_price:.2f} → {current_price:.2f}\n"
            f"{profit_emoji} P&L: <b>{current_profit*100:+.2f}%</b>\n"
            f"⏰ Время: {held_hours:.1f}ч ({held_minutes:.0f}м)\n"
            f"🤖 AI Score: {position.get('ai_score', 0):.3f}\n"
            f"🕯️ Pattern: {position.get('pattern', 'N/A')}"
        )
        
        return summary
        
    except Exception as e:
        logger.error(f"Ошибка получения сводки позиции: {e}")
        return f"❌ Ошибка: {e}"

def emergency_close_position():
    """Экстренное закрытие позиции"""
    position = get_open_position()
    if not position:
        return "📭 Нет открытых позиций для закрытия"
    
    try:
        # Генерируем текущие данные для логирования
        current_result = generate_signal()
        success = close_position(position, "🚨 Экстренное закрытие", current_result)
        
        if success:
            return "✅ Позиция экстренно закрыта"
        else:
            return "❌ Ошибка экстренного закрытия"
            
    except Exception as e:
        logger.error(f"Ошибка экстренного закрытия: {e}")
        return f"❌ Ошибка: {e}"
