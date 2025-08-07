import json
import os
from datetime import datetime
import ccxt

POSITION_FILE = "open_position.json"

def get_open_position_status():
    """Получение подробного статуса открытой позиции"""
    if not os.path.exists(POSITION_FILE):
        return "📭 Открытых позиций нет"

    try:
        with open(POSITION_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        entry_price = data.get("entry_price")
        entry_time = data.get("timestamp")
        position_type = data.get("type")
        symbol = data.get("symbol", "BTC/USDT")
        amount = data.get("amount", 0)
        ai_score = data.get("ai_score", 0)
        pattern = data.get("pattern", "N/A")
        confidence = data.get("confidence", 0)

        if not all([entry_price, entry_time, position_type]):
            return "📭 Данные позиции неполные"

        # Парсим время
        entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00') if 'Z' in entry_time else entry_time)
        now = datetime.utcnow()
        time_diff = now - entry_dt
        
        hours = int(time_diff.total_seconds() // 3600)
        minutes = int((time_diff.total_seconds() % 3600) // 60)

        # Получаем текущую цену
        try:
            exchange = ccxt.gateio()
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            
            # Расчет P&L
            if position_type == 'buy':
                pnl_percent = (current_price - entry_price) / entry_price * 100
            else:
                pnl_percent = (entry_price - current_price) / entry_price * 100
                
            pnl_usd = pnl_percent / 100 * entry_price * amount
            
            # Эмодзи для P&L
            pnl_emoji = "🟢" if pnl_percent > 0 else "🔴" if pnl_percent < 0 else "🟡"
            
        except Exception as e:
            current_price = entry_price
            pnl_percent = 0
            pnl_usd = 0
            pnl_emoji = "❓"

        # Форматирование времени
        if hours > 0:
            time_str = f"{hours}ч {minutes}м"
        else:
            time_str = f"{minutes}м"

        status = f"""📌 <b>Открытая позиция</b>

🔄 <b>Позиция:</b> {position_type.upper()}
💰 <b>Символ:</b> {symbol}
📊 <b>Количество:</b> {amount:.6f}

💵 <b>Цены:</b>
• Вход: ${entry_price:.2f}
• Текущая: ${current_price:.2f}

{pnl_emoji} <b>P&L:</b> {pnl_percent:+.2f}% (${pnl_usd:+.2f})

⏰ <b>Время:</b>
• Открыта: {entry_dt.strftime('%Y-%m-%d %H:%M')} UTC
• Удерживается: {time_str}

🤖 <b>AI данные:</b>
• Score: {ai_score:.3f}
• Pattern: {pattern}
• Confidence: {confidence:.1f}%

📈 <b>Состояние:</b> {'Прибыльная' if pnl_percent > 0 else 'Убыточная' if pnl_percent < 0 else 'На уровне'}
"""

        return status

    except Exception as e:
        return f"❌ Ошибка получения статуса позиции: {e}"

def get_position_summary():
    """Краткая сводка по позиции"""
    if not os.path.exists(POSITION_FILE):
        return "📭 Нет открытых позиций"

    try:
        with open(POSITION_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        position_type = data.get("type", "UNKNOWN")
        entry_price = data.get("entry_price", 0)
        symbol = data.get("symbol", "BTC/USDT")

        # Получаем текущую цену
        try:
            exchange = ccxt.gateio()
            current_price = exchange.fetch_ticker(symbol)['last']
            
            if position_type == 'buy':
                pnl_percent = (current_price - entry_price) / entry_price * 100
            else:
                pnl_percent = (entry_price - current_price) / entry_price * 100
                
            pnl_emoji = "🟢" if pnl_percent > 0 else "🔴"
            
        except:
            current_price = entry_price
            pnl_percent = 0
            pnl_emoji = "⚪"

        return f"{pnl_emoji} {position_type.upper()}: {entry_price:.2f}→{current_price:.2f} ({pnl_percent:+.1f}%)"

    except Exception as e:
        return f"❌ Ошибка: {e}"

def get_position_risk_analysis():
    """Анализ рисков текущей позиции"""
    if not os.path.exists(POSITION_FILE):
        return None

    try:
        with open(POSITION_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        entry_price = data.get("entry_price", 0)
        position_type = data.get("type")
        symbol = data.get("symbol", "BTC/USDT")
        entry_time = data.get("timestamp")
        
        # Время удержания
        entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00') if 'Z' in entry_time else entry_time)
        hold_hours = (datetime.utcnow() - entry_dt).total_seconds() / 3600

        # Текущая цена
        try:
            exchange = ccxt.gateio()
            current_price = exchange.fetch_ticker(symbol)['last']
        except:
            current_price = entry_price

        # Расчет рисков
        if position_type == 'buy':
            pnl_percent = (current_price - entry_price) / entry_price * 100
            risk_to_support = 0  # Можно добавить расчет до уровня поддержки
        else:
            pnl_percent = (entry_price - current_price) / entry_price * 100
            risk_to_resistance = 0  # Можно добавить расчет до уровня сопротивления

        # Оценка рисков
        risk_level = "НИЗКИЙ"
        if abs(pnl_percent) > 3:
            risk_level = "ВЫСОКИЙ"
        elif abs(pnl_percent) > 1.5:
            risk_level = "СРЕДНИЙ"

        time_risk = "НОРМАЛЬНЫЙ"
        if hold_hours > 6:
            time_risk = "ДОЛГИЙ"
        elif hold_hours > 12:
            time_risk = "КРИТИЧЕСКИЙ"

        analysis = {
            "current_pnl": pnl_percent,
            "hold_hours": hold_hours,
            "risk_level": risk_level,
            "time_risk": time_risk,
            "position_type": position_type,
            "entry_price": entry_price,
            "current_price": current_price
        }

        return analysis

    except Exception as e:
        print(f"Ошибка анализа рисков: {e}")
        return None

def format_position_alert():
    """Форматирование алерта по позиции для критических ситуаций"""
    analysis = get_position_risk_analysis()
    
    if not analysis:
        return None
        
    if analysis["risk_level"] == "ВЫСОКИЙ" or analysis["time_risk"] == "КРИТИЧЕСКИЙ":
        alert = f"""
🚨 <b>ВНИМАНИЕ: Высокий риск позиции!</b>

📊 {analysis['position_type'].upper()}: {analysis['entry_price']:.2f} → {analysis['current_price']:.2f}
📉 P&L: {analysis['current_pnl']:+.2f}%
⏰ Удерживается: {analysis['hold_hours']:.1f}ч

⚠️ Уровень риска: {analysis['risk_level']}
⏱️ Временной риск: {analysis['time_risk']}

🤖 Рекомендация: Рассмотрите закрытие позиции
"""
        return alert
        
    return None

def save_position_snapshot():
    """Сохранение снапшота позиции для анализа"""
    if not os.path.exists(POSITION_FILE):
        return False
        
    try:
        analysis = get_position_risk_analysis()
        if not analysis:
            return False
            
        snapshot = {
            "timestamp": datetime.utcnow().isoformat(),
            "analysis": analysis
        }
        
        # Сохраняем в файл снапшотов
        snapshots_file = "position_snapshots.json"
        snapshots = []
        
        if os.path.exists(snapshots_file):
            with open(snapshots_file, 'r') as f:
                snapshots = json.load(f)
                
        snapshots.append(snapshot)
        
        # Оставляем только последние 100 снапшотов
        snapshots = snapshots[-100:]
        
        with open(snapshots_file, 'w') as f:
            json.dump(snapshots, f, indent=2)
            
        return True
        
    except Exception as e:
        print(f"Ошибка сохранения снапшота: {e}")
        return False
