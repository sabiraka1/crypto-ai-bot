#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Совместимый генератор данных для Enhanced Trading System v2.0
Создает CSV с точной структурой из enhanced_data_logger.py
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import os

def generate_realistic_trading_data():
    """
    Генерация данных с ТОЧНОЙ структурой из enhanced_data_logger.py
    """
    
    # Базовые настройки
    start_date = datetime.now() - timedelta(days=14)
    data = []
    
    # Симуляция цены BTC
    base_price = 43000
    current_price = base_price
    
    # Тренды по дням
    daily_trends = ['BULLISH', 'NEUTRAL', 'BEARISH', 'BULLISH', 'NEUTRAL', 
                   'BEARISH', 'BULLISH', 'NEUTRAL', 'BEARISH', 'BULLISH',
                   'NEUTRAL', 'BEARISH', 'BULLISH', 'NEUTRAL']
    
    # RSI состояния для отслеживания 5 свечей подряд >70
    rsi_history = []
    
    # Генерация данных (каждые 15 минут = 96 записей в день)
    for day in range(14):
        current_date = start_date + timedelta(days=day)
        daily_trend = daily_trends[day]
        
        # Базовое изменение цены за день
        if daily_trend == 'BULLISH':
            daily_change = random.uniform(1.5, 4.5) / 100  # В долях, не процентах
        elif daily_trend == 'BEARISH':
            daily_change = random.uniform(-4.0, -1.0) / 100
        else:
            daily_change = random.uniform(-1.0, 1.0) / 100
        
        # 96 записей в день
        for period in range(96):
            timestamp = current_date + timedelta(minutes=period * 15)
            
            # Внутридневное движение цены
            intraday_change = random.uniform(-0.5, 0.5) / 100
            if period < 32:  # утро
                price_multiplier = 1 + (daily_change * 0.3 + intraday_change)
            elif period < 64:  # день
                price_multiplier = 1 + (daily_change * 0.4 + intraday_change)
            else:  # вечер
                price_multiplier = 1 + (daily_change * 0.3 + intraday_change)
            
            current_price *= price_multiplier
            
            # RSI с корреляцией к тренду
            if daily_trend == 'BULLISH':
                rsi = random.uniform(45, 85)
            elif daily_trend == 'BEARISH':
                rsi = random.uniform(15, 55)
            else:
                rsi = random.uniform(30, 70)
            
            # Отслеживаем RSI для логики 5 свечей подряд >70
            rsi_history.append(rsi > 70)
            if len(rsi_history) > 5:
                rsi_history.pop(0)
            
            # MACD
            macd = random.uniform(-100, 100)
            macd_signal = macd + random.uniform(-20, 20)
            macd_histogram = macd - macd_signal
            
            # Система баллов (как в enhanced_smart_risk_manager.py)
            macd_score = 0
            if macd > macd_signal:  # Пересечение вверх
                macd_score += 1
            if len(data) > 0 and macd_histogram > data[-1]['macd_histogram']:
                macd_score += 1  # Растущая гистограмма
            if 30 < rsi < 70:  # RSI поддержка
                macd_score += 1
            
            macd_contribution = macd_score * 1.2  # Приоритет MACD x1.2
            
            # Адаптивные поправки на тренд
            trend_adjustment = 0
            if daily_trend == 'BULLISH':
                trend_adjustment = -0.6  # Легче входы (-20%)
            elif daily_trend == 'BEARISH':
                trend_adjustment = 1.2   # Труднее входы (+40%)
            
            # Общий балл системы
            total_score = macd_contribution + trend_adjustment + random.uniform(-0.5, 0.5)
            
            # AI Score (имитация evaluate_signal)
            ai_score = min(0.95, max(0.1, 
                (total_score / 5.0) + random.uniform(-0.1, 0.1)
            ))
            
            # Confidence
            confidence = min(100, max(20, ai_score * 100 + random.uniform(-10, 10)))
            
            # Определение сигнала по логике enhanced_smart_risk_manager
            signal = 'HOLD'
            if total_score >= 3.0:  # MIN_SCORE_FOR_TRADE = 3
                signal = 'BUY'
            
            # Проверка условий закрытия (5 свечей RSI > 70)
            if len(rsi_history) >= 5 and all(rsi_history[-5:]):
                if signal == 'BUY':
                    signal = 'HOLD'  # Блокируем вход
            
            if rsi > 90:  # Критическое закрытие
                signal = 'CRITICAL_SELL'
            
            # Паттерны (из technical_analysis.py)
            patterns = [
                'DOJI', 'HAMMER', 'SHOOTING_STAR', 'SPINNING_TOP', 
                'BULLISH_MARUBOZU', 'BEARISH_MARUBOZU', 'BULLISH_ENGULFING',
                'BEARISH_ENGULFING', 'MORNING_STAR', 'EVENING_STAR', 'NONE'
            ]
            pattern = random.choice(patterns)
            pattern_score = random.uniform(1, 6) if pattern != 'NONE' else 0
            
            pattern_direction = 'NEUTRAL'
            if 'BULLISH' in pattern or pattern in ['HAMMER', 'MORNING_STAR']:
                pattern_direction = 'BULLISH'
            elif 'BEARISH' in pattern or pattern in ['SHOOTING_STAR', 'EVENING_STAR']:
                pattern_direction = 'BEARISH'
            elif pattern in ['DOJI', 'SPINNING_TOP']:
                pattern_direction = 'REVERSAL'
            
            # Уровни поддержки/сопротивления
            support = current_price * random.uniform(0.97, 0.99)
            resistance = current_price * random.uniform(1.01, 1.03)
            
            # Buy/Sell scores (из technical_analysis.py логики)
            buy_conditions_score = 0
            sell_conditions_score = 0
            
            # Имитируем 8 условий для каждого направления
            if rsi < 35: buy_conditions_score += 1
            if macd > macd_signal: buy_conditions_score += 1  
            if pattern_direction == 'BULLISH': buy_conditions_score += 1
            if current_price > support * 0.995: buy_conditions_score += 1
            if daily_trend == 'BULLISH': buy_conditions_score += 1
            # Добавляем еще 3 случайных условия
            buy_conditions_score += random.randint(0, 3)
            
            if rsi > 65: sell_conditions_score += 1
            if macd < macd_signal: sell_conditions_score += 1
            if pattern_direction == 'BEARISH': sell_conditions_score += 1  
            if current_price < resistance * 1.005: sell_conditions_score += 1
            if daily_trend == 'BEARISH': sell_conditions_score += 1
            # Добавляем еще 3 случайных условия
            sell_conditions_score += random.randint(0, 3)
            
            buy_score = min(8, buy_conditions_score)
            sell_score = min(8, sell_conditions_score)
            
            # Тренд 4H (может отличаться от дневного)
            trend_4h = daily_trend
            if period % 16 == 0:  # Каждые 4 часа может поменяться
                trend_4h = random.choice(['BULLISH', 'NEUTRAL', 'BEARISH'])
            
            # Состояние рынка
            price_change_24h_pct = abs(daily_change) * 100
            if price_change_24h_pct > 6:
                market_state = 'OVERHEATED_BULLISH' if daily_change > 0 else 'OVERSOLD_BEARISH'
            elif price_change_24h_pct > 3:
                market_state = 'HIGH_VOLATILITY'
            else:
                market_state = 'NORMAL'
            
            # Определение успешности (для BUY сигналов)
            success = 0
            if signal == 'BUY':
                # Логика успеха на основе будущего движения
                success_prob = 0.7 if daily_trend == 'BULLISH' else 0.4
                if macd_contribution >= 2:
                    success_prob += 0.1
                if pattern_score >= 4:
                    success_prob += 0.1
                success = 1 if random.random() < success_prob else 0
            
            # Причины (копируем логику из enhanced_smart_risk_manager)
            main_reason = f"MACD_score_{macd_score}"
            if total_score >= 3:
                main_reason += "_sufficient_score"
            if daily_trend == 'BULLISH':
                main_reason += "_bullish_trend_support"
            elif daily_trend == 'BEARISH':
                main_reason += "_bearish_trend_caution"
            
            # Добавляем запись с ТОЧНОЙ структурой из enhanced_data_logger.py
            data.append({
                # Основная информация
                'datetime': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                'signal': signal,
                'price': round(current_price, 2),
                'success': success,
                
                # Технические индикаторы  
                'rsi': round(rsi, 2),
                'macd': round(macd, 4),
                'macd_signal': round(macd_signal, 4),
                'macd_histogram': round(macd_histogram, 4),
                
                # Система баллов
                'total_score': round(total_score, 2),
                'macd_contribution': round(macd_contribution, 2),
                'ai_score': round(ai_score, 3),
                'confidence': round(confidence, 1),
                
                # Паттерны
                'pattern': pattern,
                'pattern_score': round(pattern_score, 2),
                'pattern_direction': pattern_direction,
                
                # Уровни
                'support': round(support, 2),
                'resistance': round(resistance, 2),
                'buy_score': buy_score,
                'sell_score': sell_score,
                
                # Трендовый анализ
                'trend_1d': daily_trend,
                'trend_4h': trend_4h,
                'market_state': market_state,
                'price_change_24h': round(daily_change * 100, 2),  # В процентах
                
                # Причины решения  
                'reasons_count': len(main_reason.split('_')),
                'main_reason': main_reason[:100]  # Ограничение длины
            })
    
    return data

def save_enhanced_csv(data, filename='sinyal_fiyat_analizi.csv'):
    """Сохранение с точной структурой enhanced_data_logger"""
    df = pd.DataFrame(data)
    
    # Проверяем соответствие структуре
    expected_columns = [
        'datetime', 'signal', 'price', 'success',
        'rsi', 'macd', 'macd_signal', 'macd_histogram',
        'total_score', 'macd_contribution', 'ai_score', 'confidence',
        'pattern', 'pattern_score', 'pattern_direction',
        'support', 'resistance', 'buy_score', 'sell_score',
        'trend_1d', 'trend_4h', 'market_state', 'price_change_24h',
        'reasons_count', 'main_reason'
    ]
    
    # Проверка всех колонок
    missing_cols = [col for col in expected_columns if col not in df.columns]
    if missing_cols:
        print(f"❌ Отсутствуют колонки: {missing_cols}")
        return None
    
    # Переупорядочиваем колонки в правильном порядке
    df = df[expected_columns]
    
    # Сохраняем
    df.to_csv(filename, index=False, encoding='utf-8')
    return df

def validate_with_existing_system():
    """Проверка совместимости с существующей системой"""
    print("🔍 Проверка совместимости с Enhanced Trading System...")
    
    # Проверяем импорты
    try:
        from enhanced_data_logger import create_enhanced_csv_structure
        print("✅ enhanced_data_logger импортирован")
        
        from enhanced_smart_risk_manager import EnhancedSmartRiskManager  
        risk_manager = EnhancedSmartRiskManager()
        print("✅ EnhancedSmartRiskManager импортирован")
        
        from technical_analysis import generate_signal
        print("✅ technical_analysis импортирован")
        
    except ImportError as e:
        print(f"⚠️ Ошибка импорта: {e}")
    
    # Проверяем параметры системы
    try:
        print(f"📊 Параметры системы:")
        print(f"   • MIN_SCORE_FOR_TRADE: {risk_manager.MIN_SCORE_FOR_TRADE}")
        print(f"   • CONFIDENCE_THRESHOLD: {risk_manager.CONFIDENCE_THRESHOLD}") 
        print(f"   • RSI_CONSECUTIVE_LIMIT: {risk_manager.RSI_CONSECUTIVE_LIMIT}")
        print(f"   • TRADE_TIMEOUT_HOURS: {risk_manager.TRADE_TIMEOUT_HOURS}")
        
    except Exception as e:
        print(f"⚠️ Ошибка получения параметров: {e}")

if __name__ == "__main__":
    print("🚀 Генерация совместимых торговых данных Enhanced Trading System v2.0...")
    
    # Проверка совместимости
    validate_with_existing_system()
    
    # Генерация данных
    trading_data = generate_realistic_trading_data()
    
    # Сохранение
    df = save_enhanced_csv(trading_data)
    
    if df is not None:
        # Статистика
        total_records = len(df)
        buy_signals = len(df[df['signal'] == 'BUY'])
        sell_signals = len(df[df['signal'].str.contains('SELL', na=False)])
        success_rate = df[df['success'] == 1]['success'].mean() if buy_signals > 0 else 0
        
        print(f"✅ Данные успешно сгенерированы!")
        print(f"📊 Статистика:")
        print(f"   • Всего записей: {total_records}")
        print(f"   • BUY сигналов: {buy_signals}")
        print(f"   • SELL сигналов: {sell_signals}")
        print(f"   • Успешность BUY: {success_rate:.1%}")
        print(f"   • Период данных: 14 дней (каждые 15 мин)")
        print(f"   • Файл: sinyal_fiyat_analizi.csv")
        
        # Анализ распределения
        print(f"\n📈 Распределение сигналов:")
        signal_counts = df['signal'].value_counts()
        for signal, count in signal_counts.items():
            print(f"   • {signal}: {count} ({count/total_records*100:.1f}%)")
        
        # Анализ баллов
        print(f"\n🎯 Анализ системы баллов:")
        high_score = len(df[df['total_score'] >= 3])
        print(f"   • Записи с score ≥3: {high_score} ({high_score/total_records*100:.1f}%)")
        print(f"   • Средний MACD contribution: {df['macd_contribution'].mean():.2f}")
        print(f"   • Средний AI score: {df['ai_score'].mean():.3f}")
        
        # Пример данных
        print(f"\n📋 Пример первых 3 записей:")
        example_cols = ['datetime', 'signal', 'price', 'total_score', 'macd_contribution', 'success']
        print(df[example_cols].head(3).to_string(index=False))
        
        print(f"\n🎯 Система готова к обучению AI модели!")
        print(f"💡 Следующие шаги:")
        print(f"   1. Запустите: python train_model.py")  
        print(f"   2. Протестируйте: python -c \"from telegram_bot import *; test_command_enhanced()\"")
        print(f"   3. Запустите систему: python app.py")
        
    else:
        print("❌ Ошибка генерации данных!")
