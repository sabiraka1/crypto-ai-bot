import csv
import os
from datetime import datetime
from error_logger import log_error_signal

CSV_FILE = "sinyal_fiyat_analizi.csv"
CLOSED_FILE = "closed_trades.csv"

def log_enhanced_trade(signal_decision, market_data, score, success=False):
    """
    Логирование торгового сигнала с расширенными данными новой системы
    """
    file_exists = os.path.isfile(CSV_FILE)
    
    # Извлекаем данные из новой системы
    action = signal_decision.get("action", "WAIT")
    total_score = signal_decision.get("score", 0)
    macd_contribution = signal_decision.get("macd_contribution", 0)
    trend_analysis = signal_decision.get("trend_analysis", {})
    reasons = signal_decision.get("reasons", [])
    
    # Рыночные данные
    rsi = market_data.get("rsi", 0)
    macd = market_data.get("macd", 0)
    macd_signal = market_data.get("macd_signal", 0)
    macd_histogram = market_data.get("macd_histogram", 0)
    pattern = market_data.get("pattern", "NONE")
    pattern_score = market_data.get("pattern_score", 0)
    pattern_direction = market_data.get("pattern_direction", "NEUTRAL")
    confidence = market_data.get("confidence", 0)
    price = market_data.get("price", 0)
    support = market_data.get("support", 0)
    resistance = market_data.get("resistance", 0)
    buy_score = market_data.get("buy_score", 0)
    sell_score = market_data.get("sell_score", 0)
    
    # Трендовые данные
    trend_1d = trend_analysis.get("trend_1d", "UNKNOWN")
    trend_4h = trend_analysis.get("trend_4h", "UNKNOWN")
    market_state = trend_analysis.get("market_state", "NORMAL")
    price_change_24h = trend_analysis.get("price_change_24h", 0)
    
    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        
        if not file_exists:
            # Новая расширенная структура CSV с трендовым анализом
            writer.writerow([
                # Основная информация
                'datetime', 'signal', 'price', 'success',
                
                # Технические индикаторы
                'rsi', 'macd', 'macd_signal', 'macd_histogram',
                
                # Система баллов
                'total_score', 'macd_contribution', 'ai_score', 'confidence',
                
                # Паттерны
                'pattern', 'pattern_score', 'pattern_direction',
                
                # Уровни
                'support', 'resistance', 'buy_score', 'sell_score',
                
                # Трендовый анализ
                'trend_1d', 'trend_4h', 'market_state', 'price_change_24h',
                
                # Причины решения
                'reasons_count', 'main_reason'
            ])
        
        # Подготавливаем основную причину
        main_reason = reasons[0] if reasons else "No specific reason"
        
        writer.writerow([
            # Основная информация
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            action, round(price, 2), int(success),
            
            # Технические индикаторы
            round(rsi, 2), round(macd, 4), round(macd_signal, 4), round(macd_histogram, 4),
            
            # Система баллов
            round(total_score, 2), round(macd_contribution, 1), round(score, 3), round(confidence, 1),
            
            # Паттерны
            pattern, round(pattern_score, 1), pattern_direction,
            
            # Уровни
            round(support, 2), round(resistance, 2), buy_score, sell_score,
            
            # Трендовый анализ
            trend_1d, trend_4h, market_state, round(price_change_24h * 100, 2),
            
            # Причины решения
            len(reasons), main_reason[:100]  # Ограничиваем длину причины
        ])

def log_test_trade_enhanced(signal_decision, market_data, score):
    """Логирование тестового сигнала с новой системой"""
    log_enhanced_trade(signal_decision, market_data, score, success=False)

def log_real_trade_enhanced(signal_decision, market_data, score):
    """Логирование реального торгового сигнала с новой системой"""
    log_enhanced_trade(signal_decision, market_data, score, success=True)

def log_closed_trade_enhanced(entry_data, close_data, pnl_percent, reason, signal_decision=None):
    """Логирование закрытой сделки с расширенными данными"""
    file_exists = os.path.isfile(CLOSED_FILE)
    
    with open(CLOSED_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        
        if not file_exists:
            writer.writerow([
                # Основные данные сделки
                'close_datetime', 'entry_price', 'close_price', 'pnl_percent',
                'hold_time_hours', 'reason', 'signal',
                
                # Данные входа
                'entry_rsi', 'entry_macd', 'entry_pattern', 'entry_confidence',
                'entry_total_score', 'entry_macd_contribution', 'entry_ai_score',
                
                # Данные выхода
                'exit_rsi', 'exit_macd', 'exit_pattern',
                
                # Трендовые данные
                'entry_trend_1d', 'entry_trend_4h', 'entry_market_state',
                'exit_trend_1d', 'exit_trend_4h', 'exit_market_state',
                
                # Адаптивные цели
                'adaptive_take_profit', 'adaptive_stop_loss'
            ])
        
        # Извлекаем данные
        entry_price = entry_data.get("entry_price", 0)
        close_price = close_data.get("price", 0)
        
        # Время удержания
        entry_time = datetime.fromisoformat(entry_data.get("timestamp", datetime.now().isoformat()))
        hold_hours = (datetime.now() - entry_time).total_seconds() / 3600
        
        # Данные входа
        entry_market = entry_data.get("market_data", {})
        entry_decision = entry_data.get("signal_decision", {})
        
        writer.writerow([
            # Основные данные сделки
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            round(entry_price, 4), round(close_price, 4), round(pnl_percent * 100, 2),
            round(hold_hours, 2), reason, entry_data.get("original_signal", "BUY"),
            
            # Данные входа
            round(entry_market.get("rsi", 0), 2),
            round(entry_market.get("macd", 0), 4),
            entry_market.get("pattern", "NONE"),
            round(entry_market.get("confidence", 0), 1),
            round(entry_decision.get("score", 0), 2),
            round(entry_decision.get("macd_contribution", 0), 1),
            round(entry_data.get("ai_score", 0), 3),
            
            # Данные выхода
            round(close_data.get("rsi", 0), 2),
            round(close_data.get("macd", 0), 4),
            close_data.get("pattern", "NONE"),
            
            # Трендовые данные
            entry_decision.get("trend_analysis", {}).get("trend_1d", "UNKNOWN"),
            entry_decision.get("trend_analysis", {}).get("trend_4h", "UNKNOWN"),
            entry_decision.get("trend_analysis", {}).get("market_state", "NORMAL"),
            close_data.get("trend_1d", "UNKNOWN"),
            close_data.get("trend_4h", "UNKNOWN"),
            close_data.get("market_state", "NORMAL"),
            
            # Адаптивные цели
            round(entry_data.get("targets", {}).get("take_profit_pct", 1.5), 1),
            round(entry_data.get("targets", {}).get("stop_loss_pct", 2.0), 1)
        ])

    # Логируем ошибочный сигнал если сделка убыточная
    if pnl_percent < -0.01:  # Больше 1% убытка
        error_row = {
            "signal": entry_data.get("original_signal", "BUY"),
            "score": entry_data.get("ai_score", 0),
            "rsi": entry_market.get("rsi", 0),
            "macd": entry_market.get("macd", 0),
            "price": close_price,
            "pnl_percent": pnl_percent,
            "pattern": entry_market.get("pattern", "NONE"),
            "confidence": entry_market.get("confidence", 0),
            "total_score": entry_decision.get("score", 0),
            "macd_contribution": entry_decision.get("macd_contribution", 0),
            "reasons": "; ".join(entry_decision.get("reasons", [])),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason,
            "hold_hours": hold_hours
        }
        log_error_signal(error_row)

def get_enhanced_performance(days=30):
    """Получение расширенной статистики производительности"""
    if not os.path.exists(CLOSED_FILE):
        return None
    
    try:
        import pandas as pd
        df = pd.read_csv(CLOSED_FILE)
        
        if len(df) == 0:
            return None
            
        # Фильтруем последние дни
        df['close_datetime'] = pd.to_datetime(df['close_datetime'])
        recent_df = df[df['close_datetime'] >= (datetime.now() - pd.Timedelta(days=days))]
        
        if len(recent_df) == 0:
            recent_df = df.tail(20)  # Последние 20 сделок если нет свежих
        
        total_trades = len(recent_df)
        profitable_trades = len(recent_df[recent_df['pnl_percent'] > 0])
        win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0
        
        avg_profit = recent_df['pnl_percent'].mean()
        total_profit = recent_df['pnl_percent'].sum()
        avg_hold_time = recent_df.get('hold_time_hours', pd.Series([0])).mean()
        
        # Анализ по трендам
        trend_performance = {}
        if 'entry_trend_1d' in recent_df.columns:
            for trend in ['BULLISH', 'BEARISH']:
                trend_trades = recent_df[recent_df['entry_trend_1d'] == trend]
                if len(trend_trades) > 0:
                    trend_performance[trend] = {
                        "trades": len(trend_trades),
                        "win_rate": (len(trend_trades[trend_trades['pnl_percent'] > 0]) / len(trend_trades) * 100),
                        "avg_profit": trend_trades['pnl_percent'].mean()
                    }
        
        # Анализ по MACD contribution
        macd_performance = {}
        if 'entry_macd_contribution' in recent_df.columns:
            high_macd = recent_df[recent_df['entry_macd_contribution'] >= 2]
            low_macd = recent_df[recent_df['entry_macd_contribution'] < 2]
            
            if len(high_macd) > 0:
                macd_performance["high_macd"] = {
                    "trades": len(high_macd),
                    "win_rate": (len(high_macd[high_macd['pnl_percent'] > 0]) / len(high_macd) * 100),
                    "avg_profit": high_macd['pnl_percent'].mean()
                }
            
            if len(low_macd) > 0:
                macd_performance["low_macd"] = {
                    "trades": len(low_macd),
                    "win_rate": (len(low_macd[low_macd['pnl_percent'] > 0]) / len(low_macd) * 100),
                    "avg_profit": low_macd['pnl_percent'].mean()
                }
        
        return {
            "period_days": days,
            "total_trades": total_trades,
            "profitable_trades": profitable_trades,
            "win_rate": round(win_rate, 1),
            "avg_profit": round(avg_profit, 2),
            "total_profit": round(total_profit, 2),
            "avg_hold_time": round(avg_hold_time, 1),
            "trend_performance": trend_performance,
            "macd_performance": macd_performance,
            "last_trade": recent_df.iloc[-1].to_dict() if total_trades > 0 else None
        }
        
    except Exception as e:
        print(f"Ошибка при анализе производительности: {e}")
        return None

def create_enhanced_csv_structure():
    """Создание структуры CSV файла с заголовками (для первого запуска)"""
    
    # Создаем сигналы CSV если не существует
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([
                # Основная информация
                'datetime', 'signal', 'price', 'success',
                
                # Технические индикаторы
                'rsi', 'macd', 'macd_signal', 'macd_histogram',
                
                # Система баллов
                'total_score', 'macd_contribution', 'ai_score', 'confidence',
                
                # Паттерны
                'pattern', 'pattern_score', 'pattern_direction',
                
                # Уровни
                'support', 'resistance', 'buy_score', 'sell_score',
                
                # Трендовый анализ
                'trend_1d', 'trend_4h', 'market_state', 'price_change_24h',
                
                # Причины решения
                'reasons_count', 'main_reason'
            ])
        print(f"✅ Создан файл {CSV_FILE} с новой структурой")
    
    # Создаем закрытые сделки CSV если не существует
    if not os.path.exists(CLOSED_FILE):
        with open(CLOSED_FILE, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([
                # Основные данные сделки
                'close_datetime', 'entry_price', 'close_price', 'pnl_percent',
                'hold_time_hours', 'reason', 'signal',
                
                # Данные входа
                'entry_rsi', 'entry_macd', 'entry_pattern', 'entry_confidence',
                'entry_total_score', 'entry_macd_contribution', 'entry_ai_score',
                
                # Данные выхода
                'exit_rsi', 'exit_macd', 'exit_pattern',
                
                # Трендовые данные
                'entry_trend_1d', 'entry_trend_4h', 'entry_market_state',
                'exit_trend_1d', 'exit_trend_4h', 'exit_market_state',
                
                # Адаптивные цели
                'adaptive_take_profit', 'adaptive_stop_loss'
            ])
        print(f"✅ Создан файл {CLOSED_FILE} с новой структурой")

# Для обратной совместимости
def log_trade(signal, score, price, result_data, success=False):
    """Обертка для старого API"""
    # Создаем фиктивное решение для совместимости
    fake_decision = {
        "action": signal,
        "score": score * 10,  # Конвертируем в новую шкалу
        "macd_contribution": 1,
        "reasons": ["Legacy compatibility mode"],
        "trend_analysis": {"trend_1d": "UNKNOWN", "trend_4h": "UNKNOWN", "market_state": "NORMAL"}
    }
    log_enhanced_trade(fake_decision, result_data, score, success)

def log_test_trade(signal, score, price, result_data):
    """Обертка для тестовых сигналов"""
    log_trade(signal, score, price, result_data, success=False)

def log_real_trade(signal, score, price, result_data):
    """Обертка для реальных сигналов"""
    log_trade(signal, score, price, result_data, success=True)

if __name__ == "__main__":
    # Создаем структуру CSV при прямом запуске
    create_enhanced_csv_structure()
    print("✅ CSV файлы подготовлены для новой системы")
