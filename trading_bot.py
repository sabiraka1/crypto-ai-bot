import os
import requests
from dotenv import load_dotenv
from sinyal_skorlayici import evaluate_signal
from technical_analysis import generate_signal
from grafik_olusturucu import draw_rsi_macd_chart
from profit_analysis import generate_profit_chart  # 📊 График доходности
from signal_analyzer import analyze_bad_signals  # ❌ Анализ ошибок
from data_logger import log_test_trade
from trading_bot import get_open_position
import ccxt
from train_model import train_model

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# === Отправка текстового сообщения ===
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"❌ Ошибка при отправке сообщения: {e}")

# === Отправка изображения ===
def send_telegram_photo(chat_id, image_path, caption=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        with open(image_path, 'rb') as photo:
            files = {'photo': photo}
            data = {'chat_id': chat_id}
            if caption:
                data['caption'] = caption
            requests.post(url, data=data, files=files)
    except Exception as e:
        print(f"❌ Ошибка при отправке фото: {e}")

# === Обработка команд Telegram ===
def handle_telegram_command(data):
    print("📨 Получено сообщение:", data)

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip().lower()

    if not chat_id or not text:
        return

    if text in ["/start", "start", "привет", "работаешь?", "ты тут?"]:
        send_telegram_message(chat_id, "🤖 Бот активен и работает 24/7! Напиши /test, /profit, /errors или /status.")

    elif text == "/test":
        result = generate_signal()
        signal = result.get("signal")
        rsi = result.get("rsi")
        macd = result.get("macd")
        price = result.get("price")
        patterns = result.get("patterns", [])

        score = evaluate_signal(result)
        log_test_trade(signal, score, price, rsi, macd)

        caption = (
            f"🧪 Тест сигнала\n"
            f"📊 Сигнал: {signal}\n"
            f"📉 RSI: {rsi:.2f}, 📈 MACD: {macd:.4f}\n"
            f"📌 Паттерны: {', '.join(patterns) if patterns else 'нет'}\n"
            f"🤖 Оценка AI: {score:.2f}\n"
            f"💰 Цена: {price:.2f}"
        )

        if score >= 0.7:
            action = "📈 AL" if signal == "BUY" else "📉 SAT"
            caption += f"\n✅ Рекомендация: {action}"
            image_path = draw_rsi_macd_chart(result)
            if image_path:
                send_telegram_photo(chat_id, image_path, caption)
                return

        send_telegram_message(chat_id, caption)

    elif text == "/profit":
        path, total_return = generate_profit_chart()
        if path:
            caption = (
                f"💼 Общая доходность: {total_return*100:.2f}%\n"
                f"📈 График: кумулятивная прибыль"
            )
            send_telegram_photo(chat_id, path, caption)
        else:
            send_telegram_message(chat_id, "ℹ️ Недостаточно данных для построения графика прибыли.")

    elif text == "/errors":
        summary, explanations = analyze_bad_signals()
        if not summary:
            send_telegram_message(chat_id, "ℹ️ Нет данных об ошибочных сигналах.")
            return

        message = "📉 Анализ ошибочных сигналов:\n"
        for key, value in summary.items():
            message += f"• {key}: {value}\n"
        if explanations:
            message += "\n❗ Примеры ошибок:\n" + "\n".join(explanations)
        send_telegram_message(chat_id, message)

    elif text == "/status":
        position = get_open_position()
        if not position:
            send_telegram_message(chat_id, "ℹ️ Сейчас нет открытых позиций.")
            return

        exchange = ccxt.gateio({
            'apiKey': os.getenv("GATE_API_KEY"),
            'secret': os.getenv("GATE_API_SECRET"),
            'enableRateLimit': True
        })

        symbol = position['symbol']
        entry = position['entry_price']
        amount = position['amount']
        timestamp = position['timestamp']
        now_price = exchange.fetch_ticker(symbol)['last']
        profit = ((now_price - entry) / entry) * 100
        if position['type'] == 'sell':
            profit = -profit

        message = (
            f"📈 Открытая позиция\n"
            f"Тип: {position['type'].upper()}\n"
            f"Цена входа: {entry:.2f}\n"
            f"Объём: {amount:.6f}\n"
            f"Дата открытия: {timestamp}\n"
            f"Текущая цена: {now_price:.2f}\n"
            f"📊 Прибыль: {profit:.2f}%"
        )
        send_telegram_message(chat_id, message)

    elif text == "/train":
        try:
            train_model()
            send_telegram_message(chat_id, "✅ AI-модель успешно обучена вручную.")
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Ошибка при обучении модели: {e}")

    else:
        send_telegram_message(chat_id, f"🤖 Неизвестная команда: {text}\nДоступно: /start, /test, /profit, /errors, /status, /train")
