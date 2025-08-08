import os
import logging
from flask import Flask, jsonify, request
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Импортируем основные модули проекта
try:
    from main import CryptoBot
    logger.info("Модули успешно импортированы")
except ImportError as e:
    logger.error(f"Ошибка импорта модулей: {e}")
    CryptoBot = None

@app.route('/')
def home():
    """Главная страница для проверки работы сервиса"""
    return jsonify({
        "status": "running",
        "service": "Crypto AI Bot",
        "message": "Бот работает и готов к торговле"
    })

@app.route('/health')
def health_check():
    """Health check endpoint для Render"""
    try:
        # Проверяем основные компоненты
        status = {
            "status": "healthy",
            "bot_token": "configured" if os.getenv('BOT_TOKEN') else "missing",
            "api_keys": "configured" if os.getenv('GATE_API_KEY') else "missing",
            "timestamp": str(__import__('datetime').datetime.now())
        }
        return jsonify(status)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

@app.route('/bot/start', methods=['POST'])
def start_bot():
    """Запуск бота"""
    try:
        if CryptoBot is None:
            return jsonify({"error": "Bot modules not available"}), 500
            
        # Здесь должна быть логика запуска бота
        logger.info("Получен запрос на запуск бота")
        return jsonify({"status": "Bot starting", "message": "Бот запускается..."})
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/bot/status')
def bot_status():
    """Статус бота"""
    try:
        return jsonify({
            "status": "active",
            "trade_amount": os.getenv('TRADE_AMOUNT', '50'),
            "timezone": os.getenv('TZ', 'UTC')
        })
    except Exception as e:
        logger.error(f"Ошибка получения статуса: {e}")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    # Получаем порт из переменных окружения (для Render)
    port = int(os.environ.get('PORT', 5000))
    
    # Настройки для продакшена
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Запуск Flask приложения на порту {port}")
    logger.info(f"Debug режим: {debug_mode}")
    
    # Запускаем приложение
    app.run(
        host='0.0.0.0',  # Важно для Render
        port=port,
        debug=debug_mode
    )