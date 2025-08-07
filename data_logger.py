import csv
import os
from datetime import datetime
from error_logger import log_error_signal

CSV_FILE = "sinyal_fiyat_analizi.csv"
CLOSED_FILE = "closed_trades.csv"

def log_trade(signal, score, price, result_data, success=False):
    """
    Логирует торговый сигнал с полными данными
    result_data должен содержать все данные из generate_signal()
    """
    file_exists = os.path.isfile(CSV_FILE)
    
    # Извлекаем данные из result_data
    rsi = result_data.get("rsi", 0)
    macd = result_data.get("macd", 0)
    pattern = result_data.get("pattern", "NONE")
    pattern_score = result_data.get("pattern_score", 0)
    pattern_direction = result_data.get("pattern_direction", "NEUTRAL")
    confidence = result_data.get("confidence", 0)
    support = result_data.get("support", 0)
    resistance = result_data.get("resistance", 0)
    buy_score = result_data.get("buy_score", 0)
    sell_score = result_data.get("sell_score", 0)
    
    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        
        if not file_exists:
            # Новая расширенная структура CSV
            writer.writerow([
                'datetime', 'signal', 'rsi', 'macd', 'price', 'score', 'success',
                'pattern', 'pattern_score', 'pattern_direction', 'confidence',
                'support', 'resistance', 'buy_score', 'sell_score'
            ])
        
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            signal, round(rsi, 2), round(macd, 4), round(price, 2), round(score, 3), int(success),
            pattern, round(pattern_score, 1), pattern_direction, round(confidence, 1),
            round(support, 2), round(resistance, 2), buy_score, sell_score
        ])

def log_test_trade(signal, score, price, result_data):
    """Логирует тестовый сигнал"""
    log_trade(signal, score, price, result_data, success=False)

def log_real_trade(signal, score, price, result_data):
    """Логирует реальный торговый сигнал"""
    log_trade(signal, score, price, result_data, success=True)

def log_closed_trade(entry_price, close_price, pnl_percent, reason, signal, score, result_data=None):
    """Логирует закрытую сделку с расширенными данными"""
    file_exists = os.path.isfile(CLOSED_FILE)
    
    with open(CLOSED_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        
        if not file_exists:
            writer.writerow([
                'close_datetime', 'entry_price', 'close_price', 'pnl_percent',
                'reason', 'signal', 'ai_score', 'rsi', 'macd', 'pattern', 'confidence'
            ])
        
        # Извлекаем дополнительные данные если есть
        rsi = result_data.get("rsi", 0) if result_data else 0
        macd = result_data.get("macd", 0) if result_data else 0
        pattern = result_data.get("pattern", "NONE") if result_data else "NONE"
        confidence = result_data.get("confidence", 0) if result_data else 0
        
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            round(entry_price, 4), round(close_price, 4),
            round(pnl_percent * 100, 2),
            reason, signal, round(score, 3),
            round(rsi, 2), round(macd, 4), pattern, round(confidence, 1)
        ])

    # Логируем ошибочный сигнал если сделка убыточная
    if pnl_percent < -0.01 and result_data:  # Больше 1% убытка
        error_row = {
            "signal": signal,
            "score": score,
            "rsi": result_data.get("rsi", 0),
            "macd": result_data.get("macd", 0),
            "price": close_price,
            "pnl_percent": pnl_percent,
            "pattern": result_data.get("pattern", "NONE"),
            "confidence": result_data.get("confidence", 0),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason
        }
        log_error_signal(error_row)

def get_recent_performance(days=7):
    """Возвращает статистику торговли за последние дни"""
    if not os.path.exists(CLOSED_FILE):
        return None
    
    try:
        import pandas as pd
        df = pd.read_csv(CLOSED_FILE)
        
        if len(df) == 0:
            return None
            
        # Последние сделки
        recent_df = df.tail(20)  # Последние 20 сделок
        
        total_trades = len(recent_df)
        profitable_trades = len(recent_df[recent_df['pnl_percent'] > 0])
        win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0
        avg_profit = recent_df['pnl_percent'].mean()
        total_profit = recent_df['pnl_percent'].sum()
        
        return {
            "total_trades": total_trades,
            "profitable_trades": profitable_trades,
            "win_rate": round(win_rate, 1),
            "avg_profit": round(avg_profit, 2),
            "total_profit": round(total_profit, 2),
            "last_trade": recent_df.iloc[-1].to_dict() if total_trades > 0 else None
        }
    except Exception as e:
        print(f"Ошибка при анализе производительности: {e}")
        return None
