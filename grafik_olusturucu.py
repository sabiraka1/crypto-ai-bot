import matplotlib.pyplot as plt
import os
from datetime import datetime

def draw_rsi_macd_chart(result):
    """
    Создаёт график на основе данных RSI, MACD, сигнала и свечной модели.
    Сохраняет график в папке charts/ с уникальным именем.
    Возвращает путь к изображению.
    """
    signal = result.get("signal", "NONE")
    rsi = result.get("rsi", 50)
    macd = result.get("macd", 0)
    pattern = result.get("pattern", None)
    price = result.get("price", "unknown")

    # Создание директории charts, если она не существует
    charts_dir = "charts"
    os.makedirs(charts_dir, exist_ok=True)

    # Название файла
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{charts_dir}/signal_{signal}_{timestamp}.png"

    # Создание графика
    fig, ax = plt.subplots(figsize=(10, 6))

    # Основной заголовок
    title = f"📈 Сигнал: {signal} | 💰 Цена: {price}\nRSI: {rsi} | MACD: {macd}"
    if pattern:
        title += f" | 🕯 Паттерн: {pattern}"
    ax.set_title(title, fontsize=12)

    # Нарисуем полосы
    ax.axhline(y=70, color='red', linestyle='--', label='RSI 70')
    ax.axhline(y=30, color='green', linestyle='--', label='RSI 30')
    ax.bar(["RSI", "MACD"], [rsi, macd], color=["blue", "orange"])
    
    # Отметка сигнала
    ax.text(0.5, max(rsi, macd) + 5, f"Сигнал: {signal}", ha='center', fontsize=11, color='purple')

    # Свечной паттерн
    if pattern:
        ax.text(0.5, min(rsi, macd) - 5, f"Паттерн: {pattern}", ha='center', fontsize=10, color='brown')

    ax.set_ylim(0, max(100, rsi + 20))
    ax.legend()
    plt.tight_layout()
    
    # Сохраняем
    plt.savefig(filename)
    plt.close()

    return filename
