import os
import logging
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from trading_bot import check_and_trade
from telegram_bot import handle_command
from train_model import create_basic_model
from enhanced_data_logger import create_enhanced_csv_structure
from dotenv import load_dotenv
import requests

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.environ.get('PORT', 10000))

# Настройка расширенного логирования
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def initialize_enhanced_system():
    """Инициализация улучшенной торговой системы"""
    logger.info("🚀 Инициализация Enhanced Trading System v2.0...")
    
    # 1. Создаем структуру CSV файлов под новую систему
    try:
        create_enhanced_csv_structure()
        logger.info("✅ CSV структура подготовлена")
    except Exception as e:
        logger.error(f"❌ Ошибка создания CSV структуры: {e}")
    
    # 2. Инициализация AI модели
    model_path = "models/ai_model.pkl"
    if not os.path.exists(model_path):
        logger.info("🧠 AI модель не найдена, создаю расширенную базовую модель...")
        try:
            create_basic_model()
            logger.info("✅ Базовая AI модель создана")
        except Exception as e:
            logger.error(f"❌ Ошибка создания базовой модели: {e}")
    else:
        logger.info("✅ AI модель найдена")
    
    # 3. Проверяем доступность торговой системы
    try:
        from enhanced_smart_risk_manager import EnhancedSmartRiskManager
        risk_manager = EnhancedSmartRiskManager()
        logger.info("✅ Умная система управления рисками инициализирована")
        
        # Тестируем анализ тренда
        trend_analysis = risk_manager.analyze_market_trend()
        logger.info(f"📊 Текущий тренд: {trend_analysis.get('trend_1d', 'Unknown')} (1D), {trend_analysis.get('trend_4h', 'Unknown')} (4H)")
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации системы рисков: {e}")
    
    # 4. Создаем необходимые директории
    directories = ["charts", "models"]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        logger.info(f"📁 Директория {directory} готова")
    
    logger.info("🎉 Enhanced Trading System v2.0 успешно инициализирована!")

def setup_enhanced_scheduler():
    """Настройка планировщика с улучшенными задачами"""
    scheduler = BackgroundScheduler()
    
    # Основная торговая логика каждые 15 минут
    scheduler.add_job(
        func=check_and_trade, 
        trigger="interval", 
        minutes=15, 
        id="enhanced_trading",
        max_instances=1,
        coalesce=True
    )
    
    # Анализ тренда каждый час
    def update_trend_analysis():
        try:
            from enhanced_smart_risk_manager import EnhancedSmartRiskManager
            risk_manager = EnhancedSmartRiskManager()
            risk_manager.analyze_market_trend()
            logger.info("📊 Трендовый анализ обновлен")
        except Exception as e:
            logger.error(f"Ошибка обновления тренда: {e}")
    
    scheduler.add_job(
        func=update_trend_analysis,
        trigger="interval",
        hours=1,
        id="trend_analysis",
        max_instances=1
    )
    
    # Очистка старых файлов каждые 12 часов
    from log_cleaner import schedule_cleanup
    scheduler.add_job(
        func=schedule_cleanup,
        trigger="interval",
        hours=12,
        id="enhanced_cleanup",
        max_instances=1
    )
    
    # Переобучение модели каждые 24 часа (если есть новые данные)
    def scheduled_retrain():
        try:
            from train_model import retrain_model
            retrain_model()
            logger.info("🧠 Плановое переобучение модели завершено")
        except Exception as e:
            logger.error(f"Ошибка планового переобучения: {e}")
    
    scheduler.add_job(
        func=scheduled_retrain,
        trigger="interval",
        hours=24,
        id="scheduled_retrain",
        max_instances=1
    )
    
    scheduler.start()
    logger.info("✅ Расширенный планировщик запущен")
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
initialize_enhanced_system()
scheduler = setup_enhanced_scheduler()
setup_webhook()

@app.route("/health", methods=["GET"])
def health():
    """Расширенная проверка здоровья Enhanced системы"""
    try:
        from trading_bot import get_open_position
        from enhanced_data_logger import get_enhanced_performance
        from enhanced_smart_risk_manager import EnhancedSmartRiskManager
        
        risk_manager = EnhancedSmartRiskManager()
        trend_analysis = risk_manager.get_cached_trend_analysis()
        
        health_data = {
            "service": "healthy",
            "version": "Enhanced Trading System v2.0",
            "components": {
                "scheduler": scheduler.running if scheduler else False,
                "ai_model": os.path.exists("models/ai_model.pkl"),
                "enhanced_csv": os.path.exists("sinyal_fiyat_analizi.csv"),
                "trades_data": os.path.exists("closed_trades.csv"),
                "risk_manager": True,
                "trend_analysis": trend_analysis.get("analysis_time") is not None
            },
            "trading": {
                "position_open": get_open_position() is not None,
                "trade_timeout_active": not risk_manager.check_trade_timeout(),
                "current_trend_1d": trend_analysis.get("trend_1d", "Unknown"),
                "current_trend_4h": trend_analysis.get("trend_4h", "Unknown"),
                "market_state": trend_analysis.get("market_state", "Unknown")
            },
            "performance": get_enhanced_performance(days=7),
            "system_config": {
                "confidence_threshold": risk_manager.CONFIDENCE_THRESHOLD,
                "min_score": risk_manager.MIN_SCORE_FOR_TRADE,
                "trade_timeout_hours": risk_manager.TRADE_TIMEOUT_HOURS,
                "rsi_consecutive_limit": risk_manager.RSI_CONSECUTIVE_LIMIT
            }
        }
        
        return jsonify(health_data), 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка health check: {e}")
        return {"service": "unhealthy", "error": str(e)}, 500

@app.route("/api/market-analysis", methods=["GET"])
def api_market_analysis():
    """API эндпоинт для получения анализа рынка"""
    try:
        from technical_analysis import generate_signal
        from enhanced_smart_risk_manager import EnhancedSmartRiskManager
        
        risk_manager = EnhancedSmartRiskManager()
        market_data = generate_signal()
        smart_decision = risk_manager.get_enhanced_trading_decision(market_data)
        
        response = {
            "timestamp": market_data.get("timestamp", ""),
            "price": market_data.get("price", 0),
            "decision": {
                "action": smart_decision.get("action", "WAIT"),
                "score": smart_decision.get("score", 0),
                "macd_contribution": smart_decision.get("macd_contribution", 0),
                "reasons": smart_decision.get("reasons", [])
            },
            "technical_indicators": {
                "rsi": market_data.get("rsi", 0),
                "macd": market_data.get("macd", 0),
                "pattern": market_data.get("pattern", "NONE"),
                "pattern_score": market_data.get("pattern_score", 0),
                "confidence": market_data.get("confidence", 0)
            },
            "trend_analysis": smart_decision.get("trend_analysis", {}),
            "trade_timeout_active": not risk_manager.check_trade_timeout()
        }
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка API анализа рынка: {e}")
        return {"error": str(e)}, 500

@app.route("/api/performance", methods=["GET"])
def api_performance():
    """API эндпоинт для получения статистики производительности"""
    try:
        from enhanced_data_logger import get_enhanced_performance
        
        days = request.args.get('days', 30, type=int)
        performance_data = get_enhanced_performance(days=days)
        
        if performance_data:
            return jsonify(performance_data), 200
        else:
            return {"message": "Insufficient data"}, 404
            
    except Exception as e:
        logger.error(f"❌ Ошибка API производительности: {e}")
        return {"error": str(e)}, 500

@app.route("/", methods=["GET"])
def home():
    """Главная страница с информацией о Enhanced системе"""
    return """
    <html>
        <head>
            <title>🤖 Enhanced Crypto AI Trading Bot v2.0</title>
            <style>
                body { font-family: Arial; padding: 20px; background: #f5f5f5; }
                .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 0 20px rgba(0,0,0,0.1); }
                h1 { color: #2c3e50; }
                .feature { background: #ecf0f1; padding: 15px; margin: 10px 0; border-radius: 5px; }
                .endpoint { background: #e8f8f5; padding: 10px; margin: 5px 0; border-radius: 5px; font-family: monospace; }
                .new-badge { background: #e74c3c; color: white; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🤖 Enhanced Crypto AI Trading Bot v2.0 <span class="new-badge">NEW</span></h1>
                
                <p><strong>Status:</strong> ✅ Running Enhanced System</p>
                <p><strong>Version:</strong> 2.0 - Smart Risk Management</p>
                <p><strong>Last Updated:</strong> August 2025</p>
                
                <h3>🆕 New Features v2.0:</h3>
                <div class="feature">
                    <strong>🎯 Smart Scoring System:</strong> MACD-based scoring with 3+ point threshold
                </div>
                <div class="feature">
                    <strong>🌍 Multi-timeframe Analysis:</strong> 1D/4H trend analysis with adaptive parameters
                </div>
                <div class="feature">
                    <strong>🔄 Enhanced Risk Management:</strong> 5-candle RSI analysis, 1-hour trade timeout
                </div>
                <div class="feature">
                    <strong>📊 Advanced Logging:</strong> Comprehensive trade data with trend analysis
                </div>
                
                <h3>📊 API Endpoints:</h3>
                <div class="endpoint">GET /health - Detailed system health check</div>
                <div class="endpoint">GET /alive - Basic status check</div>
                <div class="endpoint">GET /api/market-analysis - Current market analysis</div>
                <div class="endpoint">GET /api/performance?days=30 - Performance statistics</div>
                <div class="endpoint">POST /webhook - Telegram webhook (internal)</div>
                
                <h3>🤖 Enhanced Features:</h3>
                <ul>
                    <li>✅ 15+ advanced candlestick patterns</li>
                    <li>✅ Multi-level trend analysis (1D/4H/15M)</li>
                    <li>✅ Adaptive market condition responses</li>
                    <li>✅ Smart MACD scoring system</li>
                    <li>✅ Enhanced risk management with RSI memory</li>
                    <li>✅ Comprehensive performance tracking</li>
                    <li>✅ Auto model retraining with trend data</li>
                    <li>✅ 15+ Telegram commands</li>
                </ul>
                
                <h3>⚙️ System Configuration:</h3>
                <ul>
                    <li>Confidence Threshold: 55%</li>
                    <li>Minimum Score: 3 points</li>
                    <li>Trade Timeout: 1 hour</li>
                    <li>RSI Close Condition: 5 candles >70</li>
                    <li>Critical RSI: >90</li>
                    <li>Timeframe: 15 minutes</li>
                </ul>
                
                <p><em>Enhanced System developed by Züleyha & Sabir | 2025</em></p>
            </div>
        </body>
    </html>
    """, 200

@app.errorhandler(404)
def not_found(error):
    """Обработчик 404 ошибок"""
    return {
        "error": "Endpoint not found", 
        "available_endpoints": [
            "/", "/alive", "/health", "/webhook", 
            "/api/market-analysis", "/api/performance"
        ],
        "version": "Enhanced v2.0"
    }, 404

@app.errorhandler(500)
def internal_error(error):
    """Обработчик 500 ошибок"""
    logger.error(f"❌ Internal server error: {error}")
    return {
        "error": "Internal server error", 
        "message": str(error),
        "version": "Enhanced v2.0"
    }, 500

if __name__ == "__main__":
    logger.info("🚀 Запуск Enhanced Flask приложения v2.0...")
    logger.info(f"🌐 Порт: {PORT}")
    logger.info(f"📱 Bot Token: {BOT_TOKEN[:10]}...")
    logger.info(f"💬 Chat ID: {os.getenv('CHAT_ID')}")
    logger.info(f"💰 Trade Amount: ${os.getenv('TRADE_AMOUNT', '50')}")
    
    # Запуск Flask приложения
    app.run(
        host="0.0.0.0", 
        port=PORT, 
        debug=False,
        threaded=True
    ).route("/webhook", methods=["POST"])
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
        status = {
            "status": "alive",
            "version": "2.0 Enhanced",
            "scheduler": scheduler.running if scheduler else False,
            "ai_model": os.path.exists("models/ai_model.pkl"),
            "csv_structure": os.path.exists("sinyal_fiyat_analizi.csv"),
            "webhook_url": f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
        }
        
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки alive: {e}")
        return {"status": "error", "message": str(e)}, 500

@app
