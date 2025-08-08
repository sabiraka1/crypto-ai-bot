import os
import logging
from datetime import datetime
import pandas as pd
import numpy as np
from io import BytesIO

# Фикс для headless серверов - устанавливаем backend перед импортом pyplot
import matplotlib
matplotlib.use('Agg')  # Безголовый backend для серверной среды
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from telegram import Bot
from telegram.error import TelegramError
import asyncio

from config.settings import TradingConfig

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""
    
    def __init__(self):
        self.bot = Bot(token=TradingConfig.BOT_TOKEN)
        self.chat_id = TradingConfig.CHAT_ID
        
    async def send_message(self, message: str, parse_mode='Markdown'):
        """Отправка текстового сообщения"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode
            )
            logger.info(f"Сообщение отправлено: {message[:50]}...")
        except TelegramError as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
    
    async def send_chart(self, data: pd.DataFrame, title: str = "Анализ рынка"):
        """Отправка графика с техническим анализом"""
        try:
            # Создаем график
            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10))
            fig.suptitle(title, fontsize=16, fontweight='bold')
            
            # График цены и скользящих средних
            ax1.plot(data.index, data['close'], label='Цена', linewidth=2)
            if 'ema_20' in data.columns:
                ax1.plot(data.index, data['ema_20'], label='EMA 20', alpha=0.7)
            if 'ema_50' in data.columns:
                ax1.plot(data.index, data['ema_50'], label='EMA 50', alpha=0.7)
            
            ax1.set_title('Цена и скользящие средние')
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # RSI
            if 'rsi' in data.columns:
                ax2.plot(data.index, data['rsi'], label='RSI', color='orange')
                ax2.axhline(y=70, color='r', linestyle='--', alpha=0.7, label='Перекупленность')
                ax2.axhline(y=30, color='g', linestyle='--', alpha=0.7, label='Перепроданность')
                ax2.set_title('RSI (Relative Strength Index)')
                ax2.set_ylim(0, 100)
                ax2.legend()
                ax2.grid(True, alpha=0.3)
            
            # MACD
            if all(col in data.columns for col in ['macd', 'macd_signal', 'macd_histogram']):
                ax3.plot(data.index, data['macd'], label='MACD', color='blue')
                ax3.plot(data.index, data['macd_signal'], label='Signal', color='red')
                ax3.bar(data.index, data['macd_histogram'], label='Histogram', alpha=0.6)
                ax3.set_title('MACD')
                ax3.legend()
                ax3.grid(True, alpha=0.3)
            
            # Форматирование дат на осях
            for ax in [ax1, ax2, ax3]:
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
            
            plt.tight_layout()
            
            # Сохраняем график в буфер
            buffer = BytesIO()
            plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
            buffer.seek(0)
            plt.close()  # Освобождаем память
            
            # Отправляем график
            await self.bot.send_photo(
                chat_id=self.chat_id,
                photo=buffer,
                caption=f"📊 {title}\n🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
            
            logger.info("График успешно отправлен")
            
        except Exception as e:
            logger.error(f"Ошибка отправки графика: {e}")
    
    async def send_trade_notification(self, trade_type: str, symbol: str, 
                                    price: float, amount: float, reason: str = ""):
        """Отправка уведомления о сделке"""
        emoji = "🟢" if trade_type.upper() == "BUY" else "🔴"
        
        message = f"""
{emoji} **{trade_type.upper()} {symbol}**

💰 **Цена:** ${price:.6f}
📊 **Количество:** {amount}
💵 **Сумма:** ${price * amount:.2f}

📝 **Причина:** {reason}

🕒 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
        """
        
        await self.send_message(message)
    
    async def send_profit_report(self, profit: float, total_trades: int, 
                               win_rate: float, current_balance: float):
        """Отправка отчета о прибыли"""
        profit_emoji = "📈" if profit > 0 else "📉"
        
        message = f"""
{profit_emoji} **ОТЧЕТ О ТОРГОВЛЕ**

💰 **P&L:** ${profit:.2f}
📊 **Всего сделок:** {total_trades}
🎯 **Винрейт:** {win_rate:.1f}%
💳 **Текущий баланс:** ${current_balance:.2f}

🕒 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
        """
        
        await self.send_message(message)
    
    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Расчет RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def calculate_macd(self, prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        """Расчет MACD"""
        ema_fast = prices.ewm(span=fast).mean()
        ema_slow = prices.ewm(span=slow).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal).mean()
        macd_histogram = macd - macd_signal
        
        return macd, macd_signal, macd_histogram

# Синхронная обертка для использования в обычном коде
class TelegramNotifierSync:
    """Синхронная обертка для TelegramNotifier"""
    
    def __init__(self):
        self.notifier = TelegramNotifier()
    
    def send_message(self, message: str):
        """Синхронная отправка сообщения"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(self.notifier.send_message(message))
    
    def send_trade_notification(self, trade_type: str, symbol: str, 
                              price: float, amount: float, reason: str = ""):
        """Синхронная отправка уведомления о сделке"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(
            self.notifier.send_trade_notification(trade_type, symbol, price, amount, reason)
        )
