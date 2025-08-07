import logging
import requests
import matplotlib.pyplot as plt
import io
import base64
from typing import Dict, List
from config.settings import TradingConfig
from core.state_manager import StateManager

class TelegramBot:
    """Telegram бот для управления торговлей"""
    
    def __init__(self, token: str, chat_id: str, state_manager: StateManager):
        self.token = token
        self.chat_id = chat_id
        self.state = state_manager
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, text: str, parse_mode: str = "HTML"):
        """Отправка сообщения"""
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            response = requests.post(url, data=data)
            return response.json()
        except Exception as e:
            logging.error(f"Failed to send telegram message: {e}")
    
    def send_photo(self, photo_data: bytes, caption: str = ""):
        """Отправка графика"""
        try:
            url = f"{self.base_url}/sendPhoto"
            files = {"photo": photo_data}
            data = {
                "chat_id": self.chat_id,
                "caption": caption,
                "parse_mode": "HTML"
            }
            response = requests.post(url, files=files, data=data)
            return response.json()
        except Exception as e:
            logging.error(f"Failed to send telegram photo: {e}")
    
    def create_chart(self, df, title: str = "BTC/USDT Chart") -> bytes:
        """Создание графика для отправки"""
        try:
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
            
            # Основной график цены
            ax1.plot(df.index, df['close'], label='Price', linewidth=2)
            ax1.plot(df.index, df['ema_9'], label='EMA 9', alpha=0.7)
            ax1.plot(df.index, df['ema_21'], label='EMA 21', alpha=0.7)
            ax1.fill_between(df.index, df['bb_lower'], df['bb_upper'], alpha=0.2, label='Bollinger Bands')
            ax1.set_title(title)
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # RSI
            ax2.plot(df.index, df['rsi'], label='RSI', color='orange')
            ax2.axhline(y=70, color='r', linestyle='--', alpha=0.7)
            ax2.axhline(y=30, color='g', linestyle='--', alpha=0.7)
            ax2.set_ylabel('RSI')
            ax2.legend()
            ax2.grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            # Сохранение в байты
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
            buffer.seek(0)
            chart_data = buffer.getvalue()
            plt.close()
            
            return chart_data
            
        except Exception as e:
            logging.error(f"Failed to create chart: {e}")
            return b""
    
    def handle_command(self, command: str, message_text: str = "") -> str:
        """Обработка команд от пользователя"""
        try:
            if command == "/start":
                return self._handle_start()
            elif command == "/stop":
                return self._handle_stop()
            elif command == "/status":
                return self._handle_status()
            elif command == "/balance":
                return self._handle_balance()
            elif command.startswith("/position_size"):
                return self._handle_position_size(message_text)
            elif command == "/settings":
                return self._handle_settings()
            elif command == "/logs":
                return self._handle_logs()
            elif command == "/retrain":
                return self._handle_retrain()
            else:
                return "❓ Неизвестная команда. Используйте /help для списка команд."
                
        except Exception as e:
            logging.error(f"Command handling failed: {e}")
            return f"❌ Ошибка выполнения команды: {e}"
    
    def _handle_start(self) -> str:
        return """
🚀 <b>Торговый бот запущен!</b>

📊 Основные команды:
• /status - Текущее состояние
• /balance - Баланс и статистика
• /chart - График BTC/USDT
• /settings - Настройки

⚙️ Управление:
• /stop - Остановить торговлю
• /position_size 100 - Изменить размер позиции
• /retrain - Переобучить модель

🤖 AI команды:
• /ask - Спросить AI о рынке
• /predict - Прогноз на ближайшие часы
• /analyze - Глубокий анализ
        """
    
    def _handle_stop(self) -> str:
        return "🛑 Торговля остановлена"
    
    def _handle_status(self) -> str:
        state = self.state.get_trading_state()
        position = self.state.state.get("position")
        
        status_text = f"📊 <b>Статус бота:</b> {state.value}\n\n"
        
        if position:
            status_text += f"💼 <b>Текущая позиция:</b>\n"
            status_text += f"📈 {position['symbol']}\n"
            status_text += f"🏷️ Цена входа: ${position['entry_price']:.2f}\n"
            status_text += f"📊 Количество: {position['quantity']:.6f}\n"
            status_text += f"⏰ Время входа: {position['entry_time'][:19]}\n"
        else:
            status_text += "💰 Позиция закрыта\n"
        
        if self.state.is_in_cooldown():
            status_text += f"❄️ Cooldown до: {self.state.state['cooldown_until'][:19]}\n"
        
        return status_text
    
    def _handle_balance(self) -> str:
        total_trades = self.state.state.get('total_trades', 0)
        win_trades = self.state.state.get('win_trades', 0)
        total_profit = self.state.state.get('total_profit', 0.0)
        
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
        
        return f"""
💰 <b>Статистика торговли:</b>

📊 Всего сделок: {total_trades}
✅ Прибыльных: {win_trades}
📈 Win Rate: {win_rate:.1f}%
💵 Общая прибыль: ${total_profit:.2f}
💼 Размер позиции: ${TradingConfig.POSITION_SIZE_USD}
        """
    
    def _handle_settings(self) -> str:
        return f"""
⚙️ <b>Текущие настройки:</b>

📊 Символ: {TradingConfig.SYMBOL}
💰 Размер позиции: ${TradingConfig.POSITION_SIZE_USD}
🎯 Take Profit: {TradingConfig.TAKE_PROFIT_PCT}%
🛑 Stop Loss: {TradingConfig.STOP_LOSS_PCT}%
📈 RSI Overbought: {TradingConfig.RSI_OVERBOUGHT}
🔴 RSI Critical: {TradingConfig.RSI_CRITICAL}
⏰ Анализ каждые: {TradingConfig.ANALYSIS_INTERVAL} мин
❄️ Cooldown: {TradingConfig.POST_SALE_COOLDOWN} мин
        """
    
    def _handle_logs(self) -> str:
        return "📋 Последние операции будут добавлены в следующей версии"
    
    def _handle_retrain(self) -> str:
        return "🔄 Переобучение модели запущено..."
    
    def _handle_position_size(self, message_text: str) -> str:
        try:
            parts = message_text.split()
            if len(parts) >= 2:
                new_size = float(parts[1])
                if 10 <= new_size <= 1000:
                    TradingConfig.POSITION_SIZE_USD = new_size
                    return f"✅ Размер позиции изменен на ${new_size}"
                else:
                    return "❌ Размер позиции должен быть от $10 до $1000"
            else:
                return "❌ Использование: /position_size 100"
        except:
            return "❌ Неверный формат. Использование: /position_size 100"