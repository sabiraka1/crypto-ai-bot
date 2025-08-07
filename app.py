import os
import logging
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from trading_bot import check_and_trade
from telegram_bot import handle_command
from train_model import create_basic_model
from dotenv import load_dotenv
import requests

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.environ.get('PORT', 10000))

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

def initialize_model():
    """Инициализация AI модели при запуске"""
    model_path = "models/ai_model.pkl"
    if not os.path.exists(model_path):
        logger.info("🧠 AI модель не найдена, создаю базовую...")
        try:
            create_basic_model()
            logger.info("✅ Базовая AI модель создана")
        except Exception as e:
            logger.error(f"❌ Ошибка создания базовой модели: {e}")
    else:
        logger.info("✅ AI модель найдена")

def setup_scheduler():
    """Настройка планировщика задач"""
    scheduler = BackgroundScheduler()
    
    # Основная торговая логика каждые 15 минут
    scheduler.add_job(
        func=check_and_trade, 
        trigger="interval", 
        minutes=15, 
        id="check_and_trade",
        max_instances=1,
        coalesce=True
    )
    
    # Очистка старых логов каждые 6 часов
    from log_cleaner import clean_logs
    scheduler.add_job(
        func=clean_logs,
        trigger="interval",
        hours=6,
        id="clean_logs",
        max_instances=1
    )
    
    scheduler.start()
    logger.info("✅ Планировщик запущен")
    return scheduler

def setup_webhook():
    """Настройка webhook для Telegram"""
    try:
        render_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
        webhook_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        
        response = requests.post(webhook_url, json={"url": render_url}, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"📡 Webhook установлен: {render_url}")
        else:
            logger.error(f"❌ Ошибка установки webhook: {response.status_code}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка настройки webhook: {e}")

# Инициализация при запуске
initialize_model()
scheduler = setup_scheduler()
setup_webhook()

@app.route("/webhook", methods=["POST"])
def webhook():
    """Обработчик webhook от Telegram"""
    try:
        data = request.get_json()
        
        if not data:
            logger.warning("⚠️ Получены пустые данные webhook")
            return "No data", 400
        
        if "message" in data:
            handle_command(data["message"])
            logger.info(f"✅ Команда обработана: {data['message'].get('text', 'N/A')}")
        else:
            logger.warning("⚠️ Webhook без сообщения")
        
        return "OK", 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка webhook: {e}")
        return f"Error: {e}", 500

@app.route("/alive", methods=["GET"])
def alive():
    """Проверка работоспособности сервиса"""
    try:
        # Проверяем состояние основных компонентов
        status = {
            "status": "alive",
            "scheduler": scheduler.running if scheduler else False,
            "model_exists": os.path.exists("models/ai_model.pkl"),
            "webhook_url": f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
        }
        
        return status, 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки alive: {e}")
        return {"status": "error", "message": str(e)}, 500

@app.route("/health", methods=["GET"])
def health():
    """Расширенная проверка здоровья системы"""
    try:
        from trading_bot import get_open_position
        from data_logger import get_recent_performance
        
        health_data = {
            "service": "healthy",
            "components": {
                "scheduler": scheduler.running if scheduler else False,
                "ai_model": os.path.exists("models/ai_model.pkl"),
                "csv_data": os.path.exists("sinyal_fiyat_analizi.csv"),
                "trades_data": os.path.exists("closed_trades.csv")
            },
            "position": get_open_position() is not None,
            "recent_performance": get_recent_performance()
        }
        
        return health_data, 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка health check: {e}")
        return {"service": "unhealthy", "error": str(e)}, 500

@app.route("/", methods=["GET"])
def home():
    """Главная страница"""
    return """
    <html>
        <head><title>🤖 Crypto AI Trading Bot</title></head>
        <body style="font-family: Arial; padding: 20px; background: #f5f5f5;">
            <h1>🤖 Crypto AI Trading Bot</h1>
            <p><strong>Status:</strong> ✅ Running</p>
            <p><strong>Version:</strong> 2.0</p>
            <p><strong>Last Updated:</strong> August 2025</p>
            
            <h3>📊 Endpoints:</h3>
            <ul>
                <li><a href="/alive">/alive</a> - Basic health check</li>
                <li><a href="/health">/health</a> - Detailed health check</li>
                <li>/webhook - Telegram webhook (POST only)</li>
            </ul>
            
            <h3>🤖 Features:</h3>
            <ul>
                <li>✅ Advanced candlestick pattern recognition</li>
                <li>✅ AI-powered signal scoring</li>
                <li>✅ Automated trading with risk management</li>
                <li>✅ Telegram integration</li>
                <li>✅ Performance tracking & analysis</li>
                <li>✅ Auto model retraining</li>
            </ul>
            
            <p><em>Developed by Züleyha & Sabir | 2025</em></p>
        </body>
    </html>
    """, 200

@app.errorhandler(404)
def not_found(error):
    """Обработчик 404 ошибок"""
    return {"error": "Endpoint not found", "available": ["/", "/alive", "/health", "/webhook"]}, 404

@app.errorhandler(500)
def internal_error(error):
    """Обработчик 500 ошибок"""
    logger.error(f"❌ Internal server error: {error}")
    return {"error": "Internal server error", "message": str(error)}, 500

if __name__ == "__main__":
    logger.info("🚀 Запуск Flask приложения...")
    logger.info(f"🌐 Порт: {PORT}")
    logger.info(f"📱 Bot Token: {BOT_TOKEN[:10]}...")
    logger.info(f"💬 Chat ID: {os.getenv('CHAT_ID')}")
    
    # Запуск Flask приложения
    app.run(
        host="0.0.0.0", 
        port=PORT, 
        debug=False,
        threaded=True
    )
