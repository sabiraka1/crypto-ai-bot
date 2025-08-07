# position_status.py

import json
import os
from datetime import datetime

OPEN_POS_FILE = "open_position.json"

def get_open_position_status():
    if not os.path.exists(OPEN_POS_FILE):
        return "📦 Позиция не найдена (файл не существует)."

    try:
        with open(OPEN_POS_FILE, "r") as f:
            data = json.load(f)
    except Exception as e:
        return f"❌ Ошибка чтения позиции: {e}"

    if not data or "price" not in data:
        return "📦 Нет открытой позиции."

    signal = data.get("signal", "N/A")
    price = data.get("price", 0)
    timestamp = data.get("timestamp", None)

    try:
        opened = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except:
        opened = "неизвестно"

    return (
        f"📈 Открытая позиция:\n"
        f"Тип: {signal}\n"
        f"Цена входа: {price}\n"
        f"Время открытия: {opened}"
    )
