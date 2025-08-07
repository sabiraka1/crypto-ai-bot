import os
from dotenv import load_dotenv
from telebot import TeleBot

from technical_analysis import generate_signal
from sinyal_skorlayici import evaluate_signal
from enhanced_smart_risk_manager import EnhancedSmartRiskManager
from enhanced_data_logger import log_test_trade_enhanced, get_enhanced_performance
from grafik_olusturucu import draw_rsi_macd_chart
from profit_chart import generate_profit_chart
from signal_analyzer import analyze_bad_signals, get_signal_performance, recommend_improvements
from train_model import retrain_model
from error_chart import create_error_report

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = TeleBot(BOT_TOKEN)

# Инициализация умной системы
risk_manager = EnhancedSmartRiskManager()

def handle_command(message):
    """Обработка команд с новой системой"""
    text = message.get("text", "")
    chat_id = message["chat"]["id"]

    if text in ["/start", "/help"]:
        help_message = """
🤖 <b>Улучшенный Crypto AI Trading Bot v2.0</b>

📊 <b>Основные команды:</b>
🧪 /test — умный тест сигнала
📊 /status — детальный статус позиции
💰 /profit — график прибыли
📈 /stats — расширенная статистика
🌍 /market — многоуровневый анализ рынка

🔧 <b>Управление системой:</b>
🧠 /train — переобучение AI модели
❌ /errors — анализ ошибок торговли
🚨 /close — экстренное закрытие позиции
📊 /trends — анализ трендовой производительности
💡 /recommendations — рекомендации по улучшению

📈 <b>Аналитика:</b>
📉 /chart — технический анализ с графиком
🕯️ /patterns — детальный анализ паттернов
⚙️ /system — состояние торговой системы
📋 /performance — подробная производительность

🆕 <b>Новые возможности v2.0:</b>
• Многоуровневый анализ трендов (1D/4H)
• Адаптивные параметры под рынок
• Умная система баллов MACD
• Тайм-аут 1ч между сделками
• RSI анализ 5 свечей для закрытия
"""
        bot.send_message(chat_id, help_message, parse_mode='HTML')

    elif text == "/test":
        try:
            # Генерация рыночных данных
            market_data = generate_signal()
            
            # Получаем умное решение
            smart_decision = risk_manager.get_enhanced_trading_decision(market_data)
            
            # AI оценка для сравнения
            ai_score = evaluate_signal(market_data)
            
            # Создание графика
            chart_path = draw_rsi_macd_chart(market_data)
            
            # Логирование тестового сигнала
            log_test_trade_enhanced(smart_decision, market_data, ai_score)
            
            # Детальное сообщение о тесте
            test_message = risk_manager.format_enhanced_decision_message(smart_decision, market_data)
            test_message += f"\n🤖 <b>AI Подтверждение:</b> {ai_score:.3f}"
            
            # Добавляем анализ качества сигнала
            if smart_decision.get("action") == "BUY" and smart_decision.get("score", 0) >= 3:
                if ai_score >= 0.6:
                    test_message += "\n✅ <b>Сигнал готов к торговле!</b>"
                else:
                    test_message += "\n⚠️ <b>Нужно больше AI подтверждения</b>"
            
            bot.send_message(chat_id, test_message, parse_mode='HTML')
            
            # Отправка графика
            if chart_path and os.path.exists(chart_path):
                with open(chart_path, "rb") as img:
                    bot.send_photo(chat_id, img, caption="📊 Технический анализ с новой системой")
                    
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка тестирования: {e}")

    elif text == "/status":
        try:
            # Импортируем функцию из обновленного trading_bot
            from trading_bot import get_position_summary_enhanced
            status = get_position_summary_enhanced()
            bot.send_message(chat_id, status, parse_mode='HTML')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка получения статуса: {e}")

    elif text == "/market":
        try:
            # Многоуровневый анализ рынка
            market_data = generate_signal()
            smart_decision = risk_manager.get_enhanced_trading_decision(market_data)
            
            from trading_bot import format_market_analysis_enhanced
            market_analysis = format_market_analysis_enhanced(market_data, smart_decision)
            
            bot.send_message(chat_id, market_analysis, parse_mode='HTML')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка анализа рынка: {e}")

    elif text == "/stats":
        try:
            perf = get_enhanced_performance(days=30)
            if perf and perf['total_trades'] > 0:
                from trading_bot import format_performance_stats
                stats_message = format_performance_stats(perf)
                bot.send_message(chat_id, stats_message, parse_mode='HTML')
            else:
                bot.send_message(chat_id, "📊 Недостаточно данных для статистики (нужно минимум 1 сделка)")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка получения статистики: {e}")

    elif text == "/performance":
        try:
            # Детальный анализ производительности
            perf_7d = get_enhanced_performance(days=7)
            perf_30d = get_enhanced_performance(days=30)
            
            message = "📈 <b>Детальная производительность</b>\n\n"
            
            if perf_7d and perf_7d['total_trades'] > 0:
                message += f"📅 <b>За 7 дней:</b>\n"
                message += f"• Сделок: {perf_7d['total_trades']}\n"
                message += f"• Win Rate: {perf_7d['win_rate']}%\n"
                message += f"• Прибыль: {perf_7d['total_profit']:+.2f}%\n\n"
            
            if perf_30d and perf_30d['total_trades'] > 0:
                message += f"📅 <b>За 30 дней:</b>\n"
                message += f"• Сделок: {perf_30d['total_trades']}\n"
                message += f"• Win Rate: {perf_30d['win_rate']}%\n"
                message += f"• Прибыль: {perf_30d['total_profit']:+.2f}%\n"
                message += f"• Среднее время: {perf_30d['avg_hold_time']:.1f}ч\n"
            
            if not (perf_7d and perf_7d['total_trades'] > 0):
                message = "📊 Недостаточно данных для анализа производительности"
            
            bot.send_message(chat_id, message, parse_mode='HTML')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка анализа производительности: {e}")

    elif text == "/trends":
        try:
            # Анализ производительности по трендам
            perf = get_enhanced_performance(days=30)
            
            if perf and 'trend_performance' in perf:
                trend_perf = perf['trend_performance']
                
                message = "🌍 <b>Анализ по трендам рынка</b>\n\n"
                
                for trend, data in trend_perf.items():
                    emoji = "📈" if trend == "BULLISH" else "📉"
                    message += f"{emoji} <b>{trend} рынок:</b>\n"
                    message += f"• Сделок: {data['trades']}\n"
                    message += f"• Win Rate: {data['win_rate']:.1f}%\n"
                    message += f"• Ср. прибыль: {data['avg_profit']:+.2f}%\n\n"
                
                # MACD анализ
                if 'macd_performance' in perf:
                    macd_perf = perf['macd_performance']
                    message += "🎯 <b>Анализ по MACD сигналам:</b>\n"
                    
                    if 'high_macd' in macd_perf:
                        data = macd_perf['high_macd']
                        message += f"🔥 Сильные MACD (≥2 балла): {data['win_rate']:.1f}% ({data['trades']} сделок)\n"
                    
                    if 'low_macd' in macd_perf:
                        data = macd_perf['low_macd']
                        message += f"🔸 Слабые MACD (<2 балла): {data['win_rate']:.1f}% ({data['trades']} сделок)\n"
                
                bot.send_message(chat_id, message, parse_mode='HTML')
            else:
                bot.send_message(chat_id, "📊 Недостаточно данных для трендового анализа")
                
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка трендового анализа: {e}")

    elif text == "/system":
        try:
            # Состояние торговой системы
            trend_analysis = risk_manager.get_cached_trend_analysis()
            
            message = f"""
⚙️ <b>Состояние торговой системы v2.0</b>

🎯 <b>Настройки:</b>
• Confidence: ≥{risk_manager.CONFIDENCE_THRESHOLD}%
• Мин. балл: ≥{risk_manager.MIN_SCORE_FOR_TRADE}
• RSI закрытие: {risk_manager.RSI_CONSECUTIVE_LIMIT} свечей >70
• Критический RSI: >{risk_manager.RSI_EXTREME_OVERBOUGHT}
• Тайм-аут: {risk_manager.TRADE_TIMEOUT_HOURS}ч

🌍 <b>Текущий рынок:</b>
• Тренд 1D: {trend_analysis.get('trend_1d', 'Unknown')}
• Тренд 4H: {trend_analysis.get('trend_4h', 'Unknown')}
• Состояние: {trend_analysis.get('market_state', 'Normal')}
• Изменение 24ч: {trend_analysis.get('price_change_24h', 0)*100:+.1f}%

💰 <b>Торговые параметры:</b>
• Сумма: ${os.getenv('TRADE_AMOUNT', 50)}
• Take Profit: {risk_manager.BASE_TAKE_PROFIT*100:.1f}%
• Stop Loss: {risk_manager.BASE_STOP_LOSS*100:.1f}%
• Макс. время: {risk_manager.MAX_HOLD_HOURS}ч

⏰ <b>Тайм-аут:</b>
"""
            
            if risk_manager.check_trade_timeout():
                message += "✅ Готов к торговле"
            else:
                message += "⏳ Активен (ожидание между сделками)"
            
            bot.send_message(chat_id, message, parse_mode='HTML')
            
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка проверки системы: {e}")

    elif text == "/recommendations":
        try:
            recommendations = recommend_improvements()
            
            message = "💡 <b>Рекомендации по улучшению системы</b>\n\n"
            
            for i, rec in enumerate(recommendations, 1):
                message += f"{i}. {rec}\n"
            
            bot.send_message(chat_id, message, parse_mode='HTML')
            
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка получения рекомендаций: {e}")

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

    elif text == "/train":
        try:
            bot.send_message(chat_id, "🧠 Начинаю переобучение AI модели...")
            retrain_model()
            bot.send_message(chat_id, "✅ AI модель успешно переобучена под новую систему!")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка переобучения: {e}")

    elif text == "/errors":
        try:
            summary, explanations = analyze_bad_signals()
            if summary:
                error_message = "❌ <b>Анализ ошибок торговли:</b>\n\n"
                for key, value in summary.items():
                    error_message += f"• {key}: {value}\n"
                
                bot.send_message(chat_id, error_message, parse_mode='HTML')
                
                if explanations:
                    details = "\n".join(explanations[:5])
                    bot.send_message(chat_id, f"<b>Детали последних ошибок:</b>\n{details}", parse_mode='HTML')
                
                # Создаем графики ошибок
                try:
                    error_charts = create_error_report()
                    for chart_path in error_charts:
                        if os.path.exists(chart_path):
                            with open(chart_path, "rb") as img:
                                bot.send_photo(chat_id, img)
                except:
                    pass
                    
            else:
                bot.send_message(chat_id, "✅ Критических ошибок не обнаружено")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка анализа: {e}")

    elif text == "/close":
        try:
            from trading_bot import emergency_close_position_enhanced
            result = emergency_close_position_enhanced()
            bot.send_message(chat_id, result, parse_mode='HTML')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка закрытия: {e}")

    elif text == "/chart":
        try:
            market_data = generate_signal()
            chart_path = draw_rsi_macd_chart(market_data)
            
            if chart_path and os.path.exists(chart_path):
                smart_decision = risk_manager.get_enhanced_trading_decision(market_data)
                
                caption = f"""
📊 <b>Технический анализ</b>
🎯 Решение: {smart_decision.get('action', 'WAIT')}
📈 Балл: {smart_decision.get('score', 0):.1f}
🕯️ Pattern: {market_data.get('pattern', 'NONE')}
"""
                with open(chart_path, "rb") as img:
                    bot.send_photo(chat_id, img, caption=caption, parse_mode='HTML')
            else:
                bot.send_message(chat_id, "❌ Ошибка создания графика")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка: {e}")

    elif text == "/patterns":
        try:
            market_data = generate_signal()
            smart_decision = risk_manager.get_enhanced_trading_decision(market_data)
            
            patterns_message = f"""
🕯️ <b>Детальный анализ паттернов</b>

📊 <b>Текущий паттерн:</b>
• Название: <b>{market_data.get('pattern', 'NONE')}</b>
• Балл: {market_data.get('pattern_score', 0):.1f}/10
• Направление: {market_data.get('pattern_direction', 'NEUTRAL')}

🎯 <b>Вклад в решение:</b>
• Общий балл системы: {smart_decision.get('score', 0):.1f}
• MACD вклад: {smart_decision.get('macd_contribution', 0):.1f}

📈 <b>Технические показатели:</b>
• RSI: {market_data.get('rsi', 0):.1f}
• MACD: {market_data.get('macd', 0):.4f}
• Confidence: {market_data.get('confidence', 0):.1f}%

💡 <b>Интерпретация:</b>
"""
            
            pattern_score = market_data.get('pattern_score', 0)
            if pattern_score >= 6:
                patterns_message += "🔥 Очень сильный паттерн\n"
            elif pattern_score >= 4:
                patterns_message += "👍 Хороший паттерн\n"
            elif pattern_score >= 2:
                patterns_message += "🔸 Слабый паттерн\n"
            else:
                patterns_message += "❌ Паттерн отсутствует\n"
            
            # Добавляем объяснение решения
            reasons = smart_decision.get('reasons', [])
            if reasons:
                patterns_message += f"\n📋 <b>Причины решения:</b>\n"
                for reason in reasons[:3]:
                    patterns_message += f"• {reason}\n"
            
            bot.send_message(chat_id, patterns_message, parse_mode='HTML')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка анализа паттернов: {e}")

    else:
        bot.send_message(chat_id, "❓ Неизвестная команда. Используйте /help для списка всех команд.")
