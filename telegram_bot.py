import os
from dotenv import load_dotenv
from telebot import TeleBot

from technical_analysis import generate_signal
from sinyal_skorlayici import evaluate_signal
from grafik_olusturucu import draw_rsi_macd_chart
from data_logger import log_test_trade, get_recent_performance
from profit_chart import generate_profit_chart
from signal_analyzer import analyze_bad_signals
from train_model import retrain_model
from trading_bot import get_position_summary, emergency_close_position

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = TeleBot(BOT_TOKEN)

def handle_command(message):
    """Обработка команд Telegram бота"""
    text = message.get("text", "")
    chat_id = message["chat"]["id"]

    if text in ["/start", "/help"]:
        help_message = (
            "🤖 <b>Crypto AI Trading Bot</b>\n\n"
            "📌 <b>Основные команды:</b>\n"
            "🧪 /test — тест текущего сигнала\n"
            "📊 /status — статус открытой позиции\n"
            "💰 /profit — график прибыли\n"
            "📈 /stats — статистика торговли\n\n"
            "🔧 <b>Управление:</b>\n"
            "🧠 /train — переобучение AI модели\n"
            "❌ /errors — анализ ошибок\n"
            "🚨 /close — экстренное закрытие позиции\n"
            "⚙️ /settings — настройки бота\n\n"
            "📊 <b>Анализ:</b>\n"
            "📈 /chart — график с индикаторами\n"
            "🕯️ /patterns — анализ паттернов\n"
            "📉 /market — состояние рынка"
        )
        bot.send_message(chat_id, help_message, parse_mode='HTML')

    elif text == "/test":
        try:
            # Генерация и анализ сигнала
            signal_data = generate_signal()
            score = evaluate_signal(signal_data)
            
            # Создание графика
            chart_path = draw_rsi_macd_chart(signal_data)
            
            # Логирование тестового сигнала
            log_test_trade(
                signal_data["signal"],
                score,
                signal_data["price"],
                signal_data
            )
            
            # Формирование детального сообщения
            test_message = (
                f"🧪 <b>Тест сигнала</b>\n"
                f"📊 <b>{signal_data['signal']}</b> @ {signal_data['price']:.2f}\n"
                f"🤖 AI Score: <b>{score:.3f}</b>\n"
                f"🎯 Confidence: {signal_data['confidence']:.1f}%\n\n"
                f"📈 RSI: {signal_data['rsi']:.1f}\n"
                f"📉 MACD: {signal_data['macd']:.4f}\n"
                f"🕯️ Pattern: {signal_data['pattern']} ({signal_data['pattern_score']:.1f})\n"
                f"📊 Direction: {signal_data['pattern_direction']}\n\n"
                f"🎯 Buy Score: {signal_data['buy_score']}/8\n"
                f"🎯 Sell Score: {signal_data['sell_score']}/8\n"
                f"💰 Support: {signal_data['support']:.2f}\n"
                f"💰 Resistance: {signal_data['resistance']:.2f}"
            )
            
            bot.send_message(chat_id, test_message, parse_mode='HTML')
            
            # Отправка графика если он создан
            if chart_path and os.path.exists(chart_path):
                with open(chart_path, "rb") as img:
                    bot.send_photo(chat_id, img, caption="📊 График технического анализа")
                    
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка тестирования: {e}")

    elif text == "/status":
        try:
            status = get_position_summary()
            bot.send_message(chat_id, status, parse_mode='HTML')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка получения статуса: {e}")

    elif text == "/profit":
        try:
            chart_path, total_profit = generate_profit_chart()
            if chart_path and os.path.exists(chart_path):
                caption = f"📈 Общая прибыль: {total_profit*100:+.2f}%"
                with open(chart_path, "rb") as img:
                    bot.send_photo(chat_id, img, caption=caption)
            else:
                bot.send_message(chat_id, "📊 Недостаточно данных для построения графика прибыли")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка построения графика: {e}")

    elif text == "/stats":
        try:
            perf = get_recent_performance()
            if perf:
                stats_message = (
                    f"📊 <b>Статистика торговли</b>\n\n"
                    f"📈 Всего сделок: {perf['total_trades']}\n"
                    f"✅ Прибыльных: {perf['profitable_trades']}\n"
                    f"🎯 Win Rate: <b>{perf['win_rate']}%</b>\n"
                    f"💰 Средняя прибыль: {perf['avg_profit']:+.2f}%\n"
                    f"📈 Общая прибыль: <b>{perf['total_profit']:+.2f}%</b>\n\n"
                )
                
                if perf['last_trade']:
                    last = perf['last_trade']
                    stats_message += (
                        f"🔄 <b>Последняя сделка:</b>\n"
                        f"📊 {last['signal']}: {last['pnl_percent']:+.2f}%\n"
                        f"⏰ {last['close_datetime']}\n"
                        f"💭 Причина: {last['reason']}"
                    )
                
                bot.send_message(chat_id, stats_message, parse_mode='HTML')
            else:
                bot.send_message(chat_id, "📊 Нет данных для статистики")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка получения статистики: {e}")

    elif text == "/train":
        try:
            bot.send_message(chat_id, "🧠 Начинаю переобучение AI модели...")
            retrain_model()
            bot.send_message(chat_id, "✅ Модель успешно переобучена!")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка переобучения: {e}")

    elif text == "/errors":
        try:
            summary, explanations = analyze_bad_signals()
            if summary:
                error_message = "❌ <b>Анализ ошибок:</b>\n\n"
                for key, value in summary.items():
                    error_message += f"{key}: {value}\n"
                
                bot.send_message(chat_id, error_message, parse_mode='HTML')
                
                if explanations:
                    details = "\n".join(explanations[:5])
                    bot.send_message(chat_id, f"<b>Детали ошибок:</b>\n{details}", parse_mode='HTML')
            else:
                bot.send_message(chat_id, "✅ Критических ошибок не обнаружено")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка анализа: {e}")

    elif text == "/close":
        try:
            result = emergency_close_position()
            bot.send_message(chat_id, result, parse_mode='HTML')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка закрытия: {e}")

    elif text == "/chart":
        try:
            signal_data = generate_signal()
            chart_path = draw_rsi_macd_chart(signal_data)
            
            if chart_path and os.path.exists(chart_path):
                caption = (
                    f"📊 Текущий анализ\n"
                    f"📈 {signal_data['signal']} @ {signal_data['price']:.2f}\n"
                    f"🕯️ {signal_data['pattern']}"
                )
                with open(chart_path, "rb") as img:
                    bot.send_photo(chat_id, img, caption=caption)
            else:
                bot.send_message(chat_id, "❌ Ошибка создания графика")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка: {e}")

    elif text == "/patterns":
        try:
            signal_data = generate_signal()
            
            patterns_message = (
                f"🕯️ <b>Анализ паттернов</b>\n\n"
                f"📊 Pattern: <b>{signal_data['pattern']}</b>\n"
                f"⭐ Score: {signal_data['pattern_score']:.1f}/10\n"
                f"🎯 Direction: {signal_data['pattern_direction']}\n\n"
                f"📈 RSI: {signal_data['rsi']:.1f}\n"
                f"📉 MACD: {signal_data['macd']:.4f}\n"
                f"🎯 Confidence: {signal_data['confidence']:.1f}%"
            )
            
            bot.send_message(chat_id, patterns_message, parse_mode='HTML')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка анализа паттернов: {e}")

    elif text == "/market":
        try:
            signal_data = generate_signal()
            
            # Определение состояния рынка
            rsi = signal_data['rsi']
            if rsi > 70:
                market_state = "🔴 Перекуплен"
            elif rsi < 30:
                market_state = "🟢 Перепродан"
            else:
                market_state = "🟡 Нейтральный"
            
            market_message = (
                f"📊 <b>Состояние рынка</b>\n\n"
                f"💰 BTC/USDT: <b>{signal_data['price']:.2f}</b>\n"
                f"📈 Состояние: {market_state}\n"
                f"📊 RSI: {rsi:.1f}\n"
                f"📉 MACD: {signal_data['macd']:.4f}\n\n"
                f"💰 Support: {signal_data['support']:.2f}\n"
                f"💰 Resistance: {signal_data['resistance']:.2f}\n\n"
                f"🎯 Buy Conditions: {signal_data['buy_score']}/8\n"
                f"🎯 Sell Conditions: {signal_data['sell_score']}/8"
            )
            
            bot.send_message(chat_id, market_message, parse_mode='HTML')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка анализа рынка: {e}")

    elif text == "/settings":
        settings_message = (
            "⚙️ <b>Настройки бота</b>\n\n"
            f"💰 Сумма торговли: ${os.getenv('TRADE_AMOUNT', '50')}\n"
            f"🎯 Take Profit: 1.5%\n"
            f"🛑 Stop Loss: -2.0%\n"
            f"⏰ Max Hold: 4 часа\n"
            f"🤖 AI Threshold: 0.65\n\n"
            "📝 <i>Настройки можно изменить в переменных окружения</i>"
        )
        bot.send_message(chat_id, settings_message, parse_mode='HTML')

    else:
        bot.send_message(chat_id, "❓ Неизвестная команда. Используйте /help для списка команд.")
