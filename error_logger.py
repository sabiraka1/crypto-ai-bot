import pandas as pd
import os
from datetime import datetime

ERROR_FILE = "error_signals.csv"

def log_error_signal(row):
    """Логирование ошибочного сигнала с расширенными данными"""
    try:
        # Создаем расширенную запись об ошибке
        error_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "signal": row.get("signal", "UNKNOWN"),
            "price": row.get("price", 0),
            "rsi": row.get("rsi", 0),
            "macd": row.get("macd", 0),
            "score": row.get("score", 0),
            "confidence": row.get("confidence", 0),
            "pattern": row.get("pattern", "NONE"),
            "pattern_score": row.get("pattern_score", 0),
            "pattern_direction": row.get("pattern_direction", "NEUTRAL"),
            "pnl_percent": row.get("pnl_percent", 0),
            "reason": row.get("reason", "UNKNOWN"),
            "explanation": explain_error(row)
        }
        
        # Преобразуем в DataFrame
        df = pd.DataFrame([error_data])
        
        # Сохраняем в CSV
        if os.path.exists(ERROR_FILE):
            df.to_csv(ERROR_FILE, mode='a', index=False, header=False)
        else:
            df.to_csv(ERROR_FILE, index=False, header=True)
            
        print(f"✅ Ошибка записана в {ERROR_FILE}")
        
    except Exception as e:
        print(f"❌ Ошибка записи error log: {e}")

def explain_error(row):
    """Объяснение причины ошибки сигнала"""
    signal = row.get("signal", "")
    rsi = row.get("rsi", 0)
    macd = row.get("macd", 0)
    score = row.get("score", 0)
    confidence = row.get("confidence", 0)
    pattern_direction = row.get("pattern_direction", "")
    pattern_score = row.get("pattern_score", 0)
    pnl_percent = row.get("pnl_percent", 0)
    
    reasons = []
    
    # Анализ основных проблем
    if score < 0.5:
        reasons.append(f"Низкий AI score ({score:.3f})")
    
    if confidence < 50:
        reasons.append(f"Низкая уверенность ({confidence:.1f}%)")
    
    # Анализ по типу сигнала
    if "BUY" in signal:
        if rsi > 70:
            reasons.append(f"RSI перекуплен ({rsi:.1f})")
        if macd < -100:
            reasons.append(f"MACD сильно негативный ({macd:.4f})")
        if pattern_direction == "BEARISH":
            reasons.append("Медвежий паттерн противоречит BUY")
        if pattern_score < 3 and row.get("pattern", "") != "NONE":
            reasons.append(f"Слабый паттерн ({pattern_score:.1f})")
            
    elif "SELL" in signal:
        if rsi < 30:
            reasons.append(f"RSI перепродан ({rsi:.1f})")
        if macd > 100:
            reasons.append(f"MACD сильно позитивный ({macd:.4f})")
        if pattern_direction == "BULLISH":
            reasons.append("Бычий паттерн противоречит SELL")
        if pattern_score < 3 and row.get("pattern", "") != "NONE":
            reasons.append(f"Слабый паттерн ({pattern_score:.1f})")
    
    # Анализ убытка
    if pnl_percent < -0.05:  # Больше 5% убытка
        reasons.append("Критический убыток")
    elif pnl_percent < -0.02:  # Больше 2% убытка
        reasons.append("Значительный убыток")
    
    if not reasons:
        reasons.append("Неблагоприятные рыночные условия")
    
    return "; ".join(reasons)

def get_error_statistics():
    """Получение статистики по ошибкам"""
    if not os.path.exists(ERROR_FILE):
        return None
    
    try:
        df = pd.read_csv(ERROR_FILE)
        
        if len(df) == 0:
            return None
        
        stats = {
            "total_errors": len(df),
            "avg_loss": df["pnl_percent"].mean() * 100,
            "max_loss": df["pnl_percent"].min() * 100,
            "avg_rsi": df["rsi"].mean(),
            "avg_macd": df["macd"].mean(),
            "avg_score": df["score"].mean(),
            "avg_confidence": df["confidence"].mean(),
            "signal_distribution": df["signal"].value_counts().to_dict(),
            "common_reasons": get_common_error_reasons(df)
        }
        
        return stats
        
    except Exception as e:
        print(f"❌ Ошибка анализа статистики ошибок: {e}")
        return None

def get_common_error_reasons(df):
    """Анализ наиболее частых причин ошибок"""
    if "explanation" not in df.columns:
        return {}
    
    try:
        # Разбиваем объяснения на отдельные причины
        all_reasons = []
        for explanation in df["explanation"].dropna():
            reasons = explanation.split("; ")
            all_reasons.extend(reasons)
        
        # Подсчитываем частоту
        from collections import Counter
        reason_counts = Counter(all_reasons)
        
        # Возвращаем топ-5 причин
        return dict(reason_counts.most_common(5))
        
    except Exception as e:
        print(f"Ошибка анализа причин: {e}")
        return {}

def clean_old_errors(days=30):
    """Очистка старых записей об ошибках"""
    if not os.path.exists(ERROR_FILE):
        return
    
    try:
        df = pd.read_csv(ERROR_FILE)
        
        if "timestamp" not in df.columns:
            return
        
        # Преобразуем timestamp в datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Фильтруем записи за последние N дней
        cutoff_date = datetime.now() - pd.Timedelta(days=days)
        df_filtered = df[df['timestamp'] >= cutoff_date]
        
        # Сохраняем отфильтрованные данные
        df_filtered.to_csv(ERROR_FILE, index=False)
        
        removed_count = len(df) - len(df_filtered)
        print(f"🧹 Очищено {removed_count} старых записей об ошибках")
        
    except Exception as e:
        print(f"❌ Ошибка очистки error log: {e}")

def generate_error_report():
    """Генерация отчета по ошибкам"""
    stats = get_error_statistics()
    
    if not stats:
        return "📊 Нет данных об ошибках"
    
    report = f"""
📊 ОТЧЕТ ПО ОШИБКАМ

📈 Общая статистика:
• Всего ошибок: {stats['total_errors']}
• Средний убыток: {stats['avg_loss']:.2f}%
• Максимальный убыток: {stats['max_loss']:.2f}%

🤖 AI Метрики:
• Средний AI Score: {stats['avg_score']:.3f}
• Средняя уверенность: {stats['avg_confidence']:.1f}%

📊 Технические показатели:
• Средний RSI: {stats['avg_rsi']:.1f}
• Средний MACD: {stats['avg_macd']:.4f}

🎯 Распределение сигналов:"""
    
    for signal, count in stats['signal_distribution'].items():
        report += f"\n• {signal}: {count}"
    
    report += "\n\n🔍 Основные причины ошибок:"
    for reason, count in stats['common_reasons'].items():
        report += f"\n• {reason}: {count}"
    
    return report
