import os, json, logging
import ccxt
from datetime import datetime
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from enhanced_data_logger import log_real_trade_enhanced, log_closed_trade_enhanced, get_enhanced_performance
from telegram_bot import bot
from train_model import retrain_model
from enhanced_smart_risk_manager import EnhancedSmartRiskManager

load_dotenv()

CHAT_ID = os.getenv("CHAT_ID")
TRADE_AMOUNT = float(os.getenv("TRADE_AMOUNT", 50))
POSITION_FILE = "open_position.json"

logger = logging.getLogger(__name__)

# Инициализация
exchange = ccxt.gateio({
    'apiKey': os.getenv("GATE_API_KEY"),
    'secret': os.getenv("GATE_API_SECRET"),
    'enableRateLimit': True,
    'sandbox': False
})

risk_manager = EnhancedSmartRiskManager()

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
    """Сохранение позиции с расширенными данными"""
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

def close_position_enhanced(position, reason, current_result=None):
    """Закрытие позиции с новой системой логирования"""
    symbol = position['symbol']
    side = 'sell' if position['type'] == 'buy' else 'buy'
    
    try:
        # Получаем текущую цену
        ticker = exchange.fetch_ticker(symbol)
        price_now = ticker['last']
        amount = position['amount']
        entry_price = position['entry_price']
        
        # Имитация закрытия позиции (раскомментируйте для реального торгования)
        # order = exchange.create_order(symbol, 'market', side, amount)
        logger.info(f"Позиция закрыта: {side} {amount} {symbol} @ {price_now}")
        
        # Расчет прибыли/убытка
        if position['type'] == 'buy':
            profit = (price_now - entry_price) / entry_price
        else:
            profit = (entry_price - price_now) / entry_price
        
        # Время удержания
        entry_time = datetime.fromisoformat(position['timestamp'])
        hold_time = datetime.utcnow() - entry_time
        hold_hours = hold_time.total_seconds() / 3600
        
        # Подготавливаем данные для логирования
        entry_data = {
            "entry_price": entry_price,
            "timestamp": position['timestamp'],
            "original_signal": position.get('original_signal', position['type'].upper()),
            "ai_score": position.get('ai_score', 0),
            "market_data": position.get('market_data', {}),
            "signal_decision": position.get('signal_decision', {}),
            "targets": position.get('targets', {})
        }
        
        close_data = current_result if current_result else {}
        
        # Логирование закрытой сделки с новой системой
        log_closed_trade_enhanced(entry_data, close_data, profit, reason)
        
        # Формирование детального сообщения
        profit_emoji = "🟢" if profit > 0 else "🔴"
        performance_rating = get_performance_emoji(profit)
        
        # Анализ качества сделки
        entry_score = position.get('signal_decision', {}).get('score', 0)
        macd_contribution = position.get('signal_decision', {}).get('macd_contribution', 0)
        
        message = f"""
{profit_emoji} <b>Сделка закрыта</b> {performance_rating}

📊 <b>Детали сделки:</b>
• Сигнал: {position.get('original_signal', 'BUY')}
• Вход: ${entry_price:.2f} → Выход: ${price_now:.2f}
• Объем: {amount:.6f} BTC (${TRADE_AMOUNT:.0f})

💰 <b>Результат:</b>
• P&L: <b>{profit*100:+.2f}%</b>
• P&L USD: <b>${profit * entry_price * amount:+.2f}</b>
• Время удержания: {hold_hours:.1f}ч

🎯 <b>Анализ входа:</b>
• Общий балл: {entry_score:.1f}
• MACD вклад: {macd_contribution:.1f}
• AI Score: {position.get('ai_score', 0):.3f}
• Pattern: {position.get('market_data', {}).get('pattern', 'N/A')}

⚡ <b>Причина закрытия:</b>
{reason}
"""
        
        # Добавляем текущие рыночные условия
        if current_result:
            message += f"""
📈 <b>Рынок при закрытии:</b>
• RSI: {current_result.get('rsi', 0):.1f}
• MACD: {current_result.get('macd', 0):.4f}
• Pattern: {current_result.get('pattern', 'NONE')}
"""
        
        send_telegram_message(CHAT_ID, message)
        
        # Переобучение модели после закрытия
        try:
            retrain_model()
            logger.info("✅ Модель переобучена после закрытия сделки")
        except Exception as e:
            logger.error(f"Ошибка переобучения модели: {e}")
        
        # Записываем время сделки для тайм-аута
        risk_manager.record_trade_time()
        
        clear_position()
        return True
        
    except Exception as e:
        logger.error(f"Ошибка закрытия сделки: {e}")
        send_telegram_message(CHAT_ID, f"❌ Ошибка закрытия сделки: {e}")
        return False

def get_performance_emoji(profit):
    """Эмодзи для оценки качества сделки"""
    if profit > 0.03:
        return "🏆"  # Отлично > 3%
    elif profit > 0.015:
        return "🥇"  # Хорошо > 1.5%
    elif profit > 0.005:
        return "👍"  # Нормально > 0.5%
    elif profit > -0.005:
        return "😐"  # Около нуля
    elif profit > -0.015:
        return "👎"  # Небольшой убыток
    else:
        return "💥"  # Значительный убыток

def check_close_conditions_enhanced(result_data):
    """Проверка условий закрытия с новой системой"""
    position = get_open_position()
    if not position:
        return
    
    try:
        # Используем новую систему управления рисками
        should_close, reason = risk_manager.should_force_close_enhanced(position, result_data)
        
        if should_close:
            close_position_enhanced(position, reason, result_data)
            
    except Exception as e:
        logger.error(f"Ошибка проверки условий закрытия: {e}")

def open_position_enhanced(decision, market_data, ai_score):
    """Открытие новой позиции с расширенным логированием"""
    symbol = "BTC/USDT"
    action = decision["action"]
    
    try:
        ticker = exchange.fetch_ticker(symbol)
        price = ticker['last']
        amount = round(TRADE_AMOUNT / price, 6)
        side = 'buy'  # Только LONG позиции как договаривались
        
        # Имитация открытия позиции (раскомментируйте для реального торгования)
        # order = exchange.create_order(symbol, 'market', side, amount)
        logger.info(f"Позиция открыта: {side} {amount} {symbol} @ {price}")
        
        # Получаем адаптивные цели
        targets = {
            "take_profit_pct": risk_manager.BASE_TAKE_PROFIT * 100,
            "stop_loss_pct": risk_manager.BASE_STOP_LOSS * 100,
            "take_profit_price": price * (1 + risk_manager.BASE_TAKE_PROFIT),
            "stop_loss_price": price * (1 - risk_manager.BASE_STOP_LOSS)
        }
        
        # Сохранение данных позиции с полной информацией
        position_data = {
            "symbol": symbol,
            "type": side,
            "entry_price": price,
            "amount": amount,
            "timestamp": datetime.utcnow().isoformat(),
            "original_signal": action,
            "ai_score": ai_score,
            "market_data": market_data,
            "signal_decision": decision,
            "targets": targets
        }
        
        save_position(position_data)
        
        # Логирование реальной сделки с новой системой
        log_real_trade_enhanced(decision, market_data, ai_score)
        
        # Формирование детального сообщения об открытии
        trend_info = decision.get("trend_analysis", {})
        
        message = f"""
🚀 <b>Новая позиция открыта!</b>

📊 <b>Сделка:</b>
• Действие: <b>{action}</b>
• Цена входа: ${price:.2f}
• Объем: {amount:.6f} BTC
• Сумма: ${TRADE_AMOUNT:.0f}

🎯 <b>Анализ решения:</b>
• Общий балл: <b>{decision.get('score', 0):.1f}</b> (мин: 3)
• MACD вклад: {decision.get('macd_contribution', 0):.1f}
• AI Score: <b>{ai_score:.3f}</b>

📈 <b>Рыночные условия:</b>
• RSI: {market_data.get('rsi', 0):.1f}
• MACD: {market_data.get('macd', 0):.4f}
• Pattern: {market_data.get('pattern', 'NONE')} ({market_data.get('pattern_score', 0):.1f})
• Confidence: {market_data.get('confidence', 0):.1f}%

🌍 <b>Тренды:</b>
• 1D: {trend_info.get('trend_1d', 'Unknown')}
• 4H: {trend_info.get('trend_4h', 'Unknown')}
• Состояние: {trend_info.get('market_state', 'Normal')}

🎯 <b>Цели:</b>
• Take Profit: {targets['take_profit_pct']:.1f}% (${targets['take_profit_price']:.2f})
• Stop Loss: {targets['stop_loss_pct']:.1f}% (${targets['stop_loss_price']:.2f})
"""
        
        # Добавляем основные причины входа
        reasons = decision.get("reasons", [])[:3]
        if reasons:
            message += "\n💡 <b>Причины входа:</b>\n"
            for reason in reasons:
                message += f"• {reason}\n"
        
        send_telegram_message(CHAT_ID, message)
        
        return True, price
        
    except Exception as e:
        logger.error(f"Ошибка открытия позиции: {e}")
        send_telegram_message(CHAT_ID, f"❌ Ошибка открытия ордера: {e}")
        return False, 0

def format_market_analysis_enhanced(market_data, decision):
    """Форматирование расширенного рыночного анализа"""
    price = market_data.get("price", 0)
    action = decision.get("action", "WAIT")
    score = decision.get("score", 0)
    trend_analysis = decision.get("trend_analysis", {})
    
    # Эмодзи для решений
    action_emoji = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡"}
    
    message = f"""
📊 <b>Умный анализ рынка</b>

💰 BTC/USDT: <b>${price:.2f}</b>
📈 Изменение 24ч: {trend_analysis.get('price_change_24h', 0)*100:+.1f}%

{action_emoji.get(action, "⚪")} <b>Решение: {action}</b>
📊 Балл: <b>{score:.1f}</b> (мин: 3)
🎯 MACD вклад: {decision.get('macd_contribution', 0):.1f}

🌍 <b>Многоуровневый тренд:</b>
• Дневной (1D): {trend_analysis.get('trend_1d', 'Unknown')}
• 4-часовой: {trend_analysis.get('trend_4h', 'Unknown')}
• Состояние рынка: {trend_analysis.get('market_state', 'Normal')}

🔧 <b>Технические индикаторы:</b>
• RSI: {market_data.get('rsi', 0):.1f}
• MACD: {market_data.get('macd', 0):.4f} / {market_data.get('macd_signal', 0):.4f}
• Pattern: {market_data.get('pattern', 'NONE')} ({market_data.get('pattern_score', 0):.1f}/10)
• Confidence: {market_data.get('confidence', 0):.1f}%

💡 <b>Система баллов:</b>
• BUY условия: {market_data.get('buy_score', 0)}/8
• SELL условия: {market_data.get('sell_score', 0)}/8
"""
    
    # Добавляем причины решения
    reasons = decision.get("reasons", [])
    if reasons:
        message += f"\n📋 <b>Анализ ({len(reasons)} факторов):</b>\n"
        for i, reason in enumerate(reasons[:4], 1):
            message += f"{i}. {reason}\n"
    
    # Специальные предупреждения
    if decision.get("reason") == "TIMEOUT":
        message += f"\n⏰ <b>Тайм-аут:</b> Ожидание {risk_manager.TRADE_TIMEOUT_HOURS}ч между сделками"
    
    market_state = trend_analysis.get('market_state', 'NORMAL')
    if market_state == "OVERHEATED_BULLISH":
        message += "\n🔥 <b>Внимание:</b> Рынок перегрет - повышенная осторожность"
    elif market_state == "OVERSOLD_BEARISH":
        message += "\n❄️ <b>Возможность:</b> Рынок перепродан - хорошие условия для входа"
    
    return message

def check_and_trade_enhanced():
    """Основная функция торговли с новой умной системой"""
    try:
        logger.info("🧠 Запуск улучшенной системы анализа...")
        
        # Генерация технических сигналов
        market_data = generate_signal()
        if market_data.get("signal") == "ERROR":
            logger.error("❌ Ошибка генерации технических сигналов")
            send_telegram_message(CHAT_ID, "❌ Ошибка анализа рынка")
            return
        
        # Получаем решение от умной системы
        smart_decision = risk_manager.get_enhanced_trading_decision(market_data)
        
        # Оценка AI системой (для дополнительного подтверждения)
        ai_score = evaluate_signal(market_data)
        
        # Проверка условий закрытия существующих позиций
        check_close_conditions_enhanced(market_data)
        
        # Проверяем есть ли открытая позиция
        current_position = get_open_position()
        
        # Формируем анализ рынка
        market_analysis = format_market_analysis_enhanced(market_data, smart_decision)
        
        # Принимаем решение о торговле
        action = smart_decision.get("action")
        score = smart_decision.get("score", 0)
        
        if action == "BUY" and score >= 3:
            
            if current_position:
                market_analysis += "\n⚠️ <i>Позиция уже открыта, ожидаем закрытия</i>"
                send_telegram_message(CHAT_ID, market_analysis)
                
            else:
                # Дополнительная проверка AI score (двойная защита)
                if ai_score >= 0.6:
                    success, entry_price = open_position_enhanced(smart_decision, market_data, ai_score)
                    
                    if success:
                        # Отправляем статистику производительности
                        perf = get_enhanced_performance(days=30)
                        if perf and perf['total_trades'] > 0:
                            perf_msg = format_performance_stats(perf)
                            send_telegram_message(CHAT_ID, perf_msg)
                else:
                    market_analysis += f"\n🤖 <i>AI подтверждение низкое ({ai_score:.3f}), ждем лучших условий</i>"
                    send_telegram_message(CHAT_ID, market_analysis)
        
        else:
            # Отправляем анализ если есть позиция или интересные условия
            should_send_analysis = (
                current_position or 
                market_data.get("pattern_score", 0) >= 4 or
                score >= 2 or
                smart_decision.get("reason") == "TIMEOUT"
            )
            
            if should_send_analysis:
                if action == "WAIT" and score < 3:
                    market_analysis += f"\n🔸 <i>Недостаточно подтверждений для входа</i>"
                send_telegram_message(CHAT_ID, market_analysis)
        
        logger.info(f"✅ Анализ завершен: {action} | Балл: {score:.1f} | AI: {ai_score:.3f}")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_and_trade_enhanced: {e}")
        send_telegram_message(CHAT_ID, f"❌ Критическая ошибка системы: {e}")

def format_performance_stats(perf):
    """Форматирование статистики производительности"""
    message = f"""
📈 <b>Статистика за {perf['period_days']} дней:</b>

🎯 <b>Общая производительность:</b>
• Сделок: {perf['total_trades']}
• Win Rate: <b>{perf['win_rate']}%</b>
• Средняя прибыль: {perf['avg_profit']:+.2f}%
• Общая прибыль: <b>{perf['total_profit']:+.2f}%</b>
• Среднее время: {perf['avg_hold_time']:.1f}ч
"""
    
    # Анализ по трендам
    trend_perf = perf.get('trend_performance', {})
    if trend_perf:
        message += "\n📊 <b>По трендам:</b>\n"
        for trend, data in trend_perf.items():
            message += f"• {trend}: {data['win_rate']:.1f}% ({data['trades']} сделок)\n"
    
    # Анализ по MACD
    macd_perf = perf.get('macd_performance', {})
    if macd_perf:
        message += "\n🎯 <b>По MACD вкладу:</b>\n"
        if 'high_macd' in macd_perf:
            data = macd_perf['high_macd']
            message += f"• Высокий MACD (≥2): {data['win_rate']:.1f}%\n"
        if 'low_macd' in macd_perf:
            data = macd_perf['low_macd']
            message += f"• Низкий MACD (<2): {data['win_rate']:.1f}%\n"
    
    return message

def get_position_summary_enhanced():
    """Получение расширенной сводки по позиции"""
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
        held_hours = (datetime.utcnow() - entry_time).total_seconds() / 3600
        
        # Текущая прибыль
        current_profit = (current_price - entry_price) / entry_price
        profit_emoji = "🟢" if current_profit > 0 else "🔴"
        
        # Получаем цели и анализ входа
        targets = position.get('targets', {})
        signal_decision = position.get('signal_decision', {})
        market_data = position.get('market_data', {})
        
        summary = f"""
📌 <b>Открытая позиция</b> {get_performance_emoji(current_profit)}

🔄 <b>Сделка:</b>
• Сигнал: {position.get('original_signal', 'BUY')}
• Вход: ${entry_price:.2f} → Текущая: ${current_price:.2f}
• Объем: {position.get('amount', 0):.6f} BTC

{profit_emoji} <b>P&L:</b> {current_profit*100:+.2f}%
⏰ <b>Удерживается:</b> {held_hours:.1f}ч

🎯 <b>Цели:</b>
• Take Profit: {targets.get('take_profit_pct', 1.5):.1f}% (${targets.get('take_profit_price', 0):.2f})
• Stop Loss: {targets.get('stop_loss_pct', 2.0):.1f}% (${targets.get('stop_loss_price', 0):.2f})

🧠 <b>Анализ входа:</b>
• Общий балл: {signal_decision.get('score', 0):.1f}
• MACD вклад: {signal_decision.get('macd_contribution', 0):.1f}  
• AI Score: {position.get('ai_score', 0):.3f}
• Pattern: {market_data.get('pattern', 'N/A')} ({market_data.get('pattern_score', 0):.1f})

📈 <b>Условия входа:</b>
• RSI: {market_data.get('rsi', 0):.1f}
• Confidence: {market_data.get('confidence', 0):.1f}%
• Trend 1D: {signal_decision.get('trend_analysis', {}).get('trend_1d', 'Unknown')}
"""
        
        return summary
        
    except Exception as e:
        logger.error(f"Ошибка получения сводки позиции: {e}")
        return f"❌ Ошибка: {e}"

def emergency_close_position_enhanced():
    """Экстренное закрытие с новой системой"""
    position = get_open_position()
    if not position:
        return "📭 Нет открытых позиций для закрытия"
    
    try:
        current_market = generate_signal()
        success = close_position_enhanced(position, "🚨 Экстренное закрытие пользователем", current_market)
        
        if success:
            return "✅ Позиция экстренно закрыта"
        else:
            return "❌ Ошибка экстренного закрытия"
            
    except Exception as e:
        logger.error(f"Ошибка экстренного закрытия: {e}")
        return f"❌ Ошибка: {e}"

# Основная функция для планировщика
def check_and_trade():
    """Обертка для основной функции (для совместимости с планировщиком)"""
    check_and_trade_enhanced()
