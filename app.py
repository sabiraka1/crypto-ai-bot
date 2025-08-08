from flask import Flask, request, jsonify
import logging
import threading
import time
import os
from main import TradingBot

app = Flask(__name__)

# Глобальная переменная для бота
trading_bot = None
bot_thread = None

@app.route('/webhook', methods=['POST'])
def webhook():
    """Webhook для Telegram"""
    try:
        data = request.get_json()
        
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            
            # Обработка команд
            if text.startswith('/'):
                response = trading_bot.telegram_bot.handle_command(text)
                trading_bot.telegram_bot.send_message(response)
        
        return jsonify({'status': 'ok'})
        
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check для Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time(),
        'bot_running': bot_thread and bot_thread.is_alive()
    })

@app.route('/start_bot', methods=['POST'])
def start_bot():
    """Запуск торгового бота"""
    global trading_bot, bot_thread
    
    try:
        if bot_thread and bot_thread.is_alive():
            return jsonify({'status': 'already_running'})
        
        trading_bot = TradingBot()
        bot_thread = threading.Thread(target=trading_bot.run, daemon=True)
        bot_thread.start()
        
        return jsonify({'status': 'started'})
        
    except Exception as e:
        logging.error(f"Failed to start bot: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    # Автозапуск бота при старте приложения
    try:
        trading_bot = TradingBot()
        bot_thread = threading.Thread(target=trading_bot.run, daemon=True)
        bot_thread.start()
        logging.info("🚀 Trading bot auto-started")
    except Exception as e:
        logging.error(f"Failed to auto-start bot: {e}")
    
    # Запуск Flask приложения
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
