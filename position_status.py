# position_status.py

import json
import os
from datetime import datetime

POSITION_FILE = "open_position.json"

def get_open_position_status():
    if not os.path.exists(POSITION_FILE):
        return "📭 Открытая позиция не найдена."

    with open(POSITION_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    entry_price = data.get("entry_price")
    entry_time = data.get("entry_time")
    position_type = data.get("type")

    if not all([entry_price, entry_time, position_type]):
        return "📭 Открытая позиция не найдена."

    # Преобразуем время
    time_fmt = "%Y-%m-%d %H:%M:%S"
    entry_dt = datetime.strptime(entry_time, time_fmt)
    duration = datetime.now() - entry_dt
    minutes = int(duration.total_seconds() // 60)

    return (
        f"📌 Открытая позиция:\n"
        f"Тип: {position_type.upper()}\n"
        f"Цена входа: {entry_price}\n"
        f"Открыта: {entry_time}\n"
        f"Прошло: {minutes} мин"
    )
