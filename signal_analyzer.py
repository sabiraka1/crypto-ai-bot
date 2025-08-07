import pandas as pd
import os

CSV_FILE = "sinyal_fiyat_analizi.csv"

def analyze_bad_signals(limit=5):
    """Анализ неудачных сигналов с расширенными данными"""
    if not os.path.exists(CSV_FILE):
        return None, None

    try:
        df = pd.read_csv(CSV_FILE, on_bad_lines='skip')
    except Exception as e:
        print(f"Ошибка чтения CSV: {e}")
        return None, None

    if len(df) < 10:
        return None, None

    # Проверяем наличие основных колонок
    required_cols = {"success", "rsi", "macd", "signal"}
    if not required_cols.issubset(df.columns):
        print(f"Отсутствуют колонки: {required_cols - set(df.columns)}")
        return None, None

    # Анализируем неудачные сигналы
    bad_signals = df[df["success"] == 0].copy()
    if bad_signals.empty:
        return None, None

    # Расширенная статистика
    summary = {
        "❌ Всего ошибок": len(bad_signals),
        "📊 Общий Win Rate": f"{(1 - len(bad_signals)/len(df))*100:.1f}%",
        "📉 Ср. RSI ошибок": round(bad_signals["rsi"].mean(), 2),
        "📉 Ср. MACD ошибок": round(bad_signals["macd"].mean(), 4),
        "⚖️ BUY ошибок": len(bad_signals[bad_signals["signal"].str.contains("BUY", na=False)]),
        "⚖️ SELL ошибок": len(bad_signals[bad_signals["signal"].str.contains("SELL", na=False)])
    }

    # Добавляем новые метрики если колонки есть
    if "score" in bad_signals.columns:
        summary["🤖 Ср. AI Score ошибок"] = round(bad_signals["score"].mean(), 3)
    
    if "confidence" in bad_signals.columns:
        summary["🎯 Ср. Confidence ошибок"] = round(bad_signals["confidence"].mean(), 1)
    
    if "pattern_score" in bad_signals.columns:
        summary["🕯️ Ср. Pattern Score ошибок"] = round(bad_signals["pattern_score"].mean(), 1)

    # Анализ паттернов ошибок
    explanations = []
    for _, row in bad_signals.tail(limit).iterrows():
        explanation = explain_signal(row)
        explanations.append(explanation)

    return summary, explanations

def explain_signal(row):
    """Расширенное объяснение причин неудачного сигнала"""
    signal = row.get("signal", "")
    rsi = row.get("rsi", 0)
    macd = row.get("macd", 0)
    score = row.get("score", 0.0)
    price = row.get("price", 0.0)
    confidence = row.get("confidence", 0)
    pattern = row.get("pattern", "")
    pattern_score = row.get("pattern_score", 0)
    pattern_direction = row.get("pattern_direction", "")
    buy_score = row.get("buy_score", 0)
    sell_score = row.get("sell_score", 0)

    comments = []

    if "BUY" in signal:
        # Анализ BUY сигналов
        if rsi > 65: 
            comments.append(f"RSI был высоким ({rsi:.1f})")
        if macd < -50: 
            comments.append(f"MACD сильно отрицательный ({macd:.4f})")
        if confidence < 50: 
            comments.append(f"Низкая уверенность ({confidence:.1f}%)")
        if pattern_direction == "BEARISH": 
            comments.append(f"Медвежий паттерн ({pattern})")
        if pattern_score < 3 and pattern != "NONE": 
            comments.append(f"Слабый паттерн ({pattern_score:.1f})")
        if buy_score < 3: 
            comments.append(f"Мало BUY условий ({buy_score}/8)")
        if score < 0.5: 
            comments.append(f"Низкий AI score ({score:.3f})")
        
        if not comments: 
            comments.append("Рынок развернулся против позиции")
            
        return f"❌ {signal} @ {price:.2f} — {'; '.join(comments)}"

    elif "SELL" in signal:
        # Анализ SELL сигналов
        if rsi < 35: 
            comments.append(f"RSI был низким ({rsi:.1f})")
        if macd > 50: 
            comments.append(f"MACD сильно положительный ({macd:.4f})")
        if confidence < 50: 
            comments.append(f"Низкая уверенность ({confidence:.1f}%)")
        if pattern_direction == "BULLISH": 
            comments.append(f"Бычий паттерн ({pattern})")
        if pattern_score < 3 and pattern != "NONE": 
            comments.append(f"Слабый паттерн ({pattern_score:.1f})")
        if sell_score < 3: 
            comments.append(f"Мало SELL условий ({sell_score}/8)")
        if score < 0.5: 
            comments.append(f"Низкий AI score ({score:.3f})")
        
        if not comments: 
            comments.append("Рынок развернулся против позиции")
            
        return f"❌ {signal} @ {price:.2f} — {'; '.join(comments)}"

    return f"❌ {signal} @ {price:.2f} — Неопределенная ошибка"

def get_pattern_statistics():
    """Статистика по паттернам"""
    if not os.path.exists(CSV_FILE):
        return None

    try:
        df = pd.read_csv(CSV_FILE)
        
        if "pattern" not in df.columns:
            return None
            
        # Статистика по паттернам
        pattern_stats = df.groupby('pattern').agg({
            'success': ['count', 'sum', 'mean'],
            'score': 'mean',
            'confidence': 'mean'
        }).round(3)
        
        return pattern_stats
        
    except Exception as e:
        print(f"Ошибка анализа паттернов: {e}")
        return None

def get_signal_performance():
    """Анализ производительности по типам сигналов"""
    if not os.path.exists(CSV_FILE):
        return None

    try:
        df = pd.read_csv(CSV_FILE)
        
        signal_performance = {}
        
        for signal_type in ["BUY", "STRONG_BUY", "SELL", "STRONG_SELL", "HOLD"]:
            signal_data = df[df["signal"] == signal_type]
            
            if len(signal_data) > 0:
                signal_performance[signal_type] = {
                    "count": len(signal_data),
                    "success_rate": (signal_data["success"].mean() * 100),
                    "avg_score": signal_data.get("score", pd.Series([0])).mean(),
                    "avg_confidence": signal_data.get("confidence", pd.Series([0])).mean(),
                    "avg_rsi": signal_data["rsi"].mean(),
                    "avg_macd": signal_data["macd"].mean()
                }
        
        return signal_performance
        
    except Exception as e:
        print(f"Ошибка анализа производительности: {e}")
        return None

def recommend_improvements():
    """Рекомендации по улучшению на основе анализа ошибок"""
    try:
        df = pd.read_csv(CSV_FILE)
        bad_signals = df[df["success"] == 0]
        
        if len(bad_signals) == 0:
            return ["✅ Ошибок не обнаружено, система работает отлично!"]
        
        recommendations = []
        
        # Анализ RSI
        if bad_signals["rsi"].mean() > 65:
            recommendations.append("📈 Увеличить порог RSI для BUY сигналов (много ошибок при высоком RSI)")
        elif bad_signals["rsi"].mean() < 35:
            recommendations.append("📉 Увеличить порог RSI для SELL сигналов (много ошибок при низком RSI)")
        
        # Анализ confidence
        if "confidence" in bad_signals.columns:
            if bad_signals["confidence"].mean() < 60:
                recommendations.append("🎯 Повысить минимальный порог confidence до 70%")
        
        # Анализ AI score
        if "score" in bad_signals.columns:
            if bad_signals["score"].mean() < 0.6:
                recommendations.append("🤖 Повысить минимальный AI score до 0.7")
        
        # Анализ паттернов
        if "pattern_score" in bad_signals.columns:
            if bad_signals["pattern_score"].mean() < 4:
                recommendations.append("🕯️ Использовать только паттерны с score >= 5")
        
        return recommendations if recommendations else ["📊 Требуется больше данных для анализа"]
        
    except Exception as e:
        return [f"❌ Ошибка анализа: {e}"]
