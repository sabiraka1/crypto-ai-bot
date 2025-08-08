import logging
import time
import pandas as pd
import schedule
from datetime import datetime, timedelta
import os
import numpy as np

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)

# Импорты наших модулей
from config.settings import TradingConfig, TradingState, MarketCondition
from core.state_manager import StateManager
from core.exceptions import *
from analysis.market_analyzer import MultiTimeframeAnalyzer
from analysis.technical_indicators import TechnicalIndicators
from analysis.scoring_engine import ScoringEngine
from trading.exchange_client import ExchangeClient
from trading.position_manager import PositionManager
from telegram.bot_handler import TelegramBot
from ml.adaptive_model import AdaptiveMLModel
from utils.csv_handler import CSVHandler

class TradingBot:
    """Основной класс торгового бота"""
    
    def __init__(self):
        self.state_manager = StateManager()
        self.exchange_client = ExchangeClient()
        self.position_manager = PositionManager(self.exchange_client, self.state_manager)
        self.market_analyzer = MultiTimeframeAnalyzer()
        self.scoring_engine = ScoringEngine()
        self.telegram_bot = TelegramBot(
            TradingConfig.BOT_TOKEN,
            TradingConfig.CHAT_ID,
            self.state_manager
        )
        self.ml_model = AdaptiveMLModel()
        
        # Загрузка ML модели
        self.ml_model.load_models()
        
        # Счетчики для анализа
        self.rsi_over_70_candles = 0
        self.last_market_reevaluation = datetime.now()
        
        logging.info("🚀 Trading bot initialized")
    
    def run(self):
        """Запуск основного цикла бота"""
        try:
            # Планирование задач
            schedule.every(TradingConfig.ANALYSIS_INTERVAL).minutes.do(self.main_trading_cycle)
            schedule.every(TradingConfig.MARKET_REEVALUATION).hours.do(self.reevaluate_market)
            
            # Отправка уведомления о запуске
            self.telegram_bot.send_message("🚀 Торговый бот запущен и готов к работе!")
            
            logging.info("📊 Bot started, entering main loop...")
            
            while True:
                schedule.run_pending()
                time.sleep(60)  # Проверка каждую минуту
                
        except KeyboardInterrupt:
            logging.info("🛑 Bot stopped by user")
            self.telegram_bot.send_message("🛑 Торговый бот остановлен")
        except Exception as e:
            logging.critical(f"Critical error in main loop: {e}")
            self.telegram_bot.send_message(f"🚨 Критическая ошибка: {e}")
    
    def main_trading_cycle(self):
        """Основной торговый цикл (каждые 15 минут)"""
        try:
            logging.info("🔄 Starting trading cycle...")
            
            # Проверка состояния cooldown
            if self.state_manager.is_in_cooldown():
                logging.info("❄️ Bot in cooldown, skipping cycle")
                return
            
            # Получение данных
            df_15m = self._fetch_market_data('15m', 100)
            df_1h = self._fetch_market_data('1h', 100)
            df_4h = self._fetch_market_data('4h', 100)
            df_1d = self._fetch_market_data('1d', 100)
            
            if any(df is None for df in [df_15m, df_1h, df_4h, df_1d]):
                logging.error("Failed to fetch market data")
                return
            
            # Расчет технических индикаторов
            df_15m = TechnicalIndicators.calculate_all_indicators(df_15m)
            
            # Анализ рынка
            market_condition, market_confidence = self.market_analyzer.analyze_market_condition(df_1d, df_4h)
            
            # ML предсказание
            ml_prediction, ml_confidence = self._get_ml_prediction(df_15m, market_condition)
            
            # Проверка текущего состояния
            current_state = self.state_manager.get_trading_state()
            
            if current_state == TradingState.WAITING:
                self._handle_waiting_state(df_15m, market_condition, ml_confidence)
            elif current_state == TradingState.IN_POSITION:
                self._handle_position_state(df_15m)
            
            # Обновление счетчика RSI
            self._update_rsi_counter(df_15m)
            
        except Exception as e:
            logging.error(f"Error in trading cycle: {e}")
            self.telegram_bot.send_message(f"⚠️ Ошибка в торговом цикле: {e}")
    
    def _handle_waiting_state(self, df: pd.DataFrame, market_condition: MarketCondition, ml_confidence: float):
        """Обработка состояния ожидания"""
        try:
            # Расчет балла для покупки
            buy_score, score_details = self.scoring_engine.calculate_buy_score(
                df, market_condition, ml_confidence
            )
            
            # Проверка условий для покупки
            if buy_score >= score_details.get('threshold', TradingConfig.MIN_SCORE_TO_BUY):
                position = self.position_manager.open_position(
                    TradingConfig.SYMBOL,
                    TradingConfig.POSITION_SIZE_USD
                )
                
                if position:
                    message = f"""
🎯 <b>ПОЗИЦИЯ ОТКРЫТА</b>

📊 {position['symbol']}
💰 Цена входа: ${position['entry_price']:.2f}
📈 Количество: {position['quantity']:.6f}
🎯 Балл решения: {buy_score:.2f}/{score_details['threshold']:.2f}
🤖 AI уверенность: {ml_confidence:.1%}
📊 Рынок: {market_condition.value}

🎯 Take Profit: {TradingConfig.TAKE_PROFIT_PCT}%
🛑 Stop Loss: {TradingConfig.STOP_LOSS_PCT}%
                    """
                    self.telegram_bot.send_message(message)
                    
        except Exception as e:
            logging.error(f"Error in waiting state: {e}")
    
    def _handle_position_state(self, df: pd.DataFrame):
        """Обработка состояния с открытой позицией"""
        try:
            position_profit = self.position_manager.get_position_profit()
            
            # Проверка условий для продажи
            should_sell, sell_reason = self.scoring_engine.should_sell(
                df, position_profit, self.rsi_over_70_candles
            )
            
            if should_sell:
                result = self.position_manager.close_position(sell_reason)
                
                if result:
                    profit_emoji = "💚" if result['profit_pct'] > 0 else "❌"
                    message = f"""
{profit_emoji} <b>ПОЗИЦИЯ ЗАКРЫТА</b>

📊 {result['symbol']}
💰 Цена выхода: ${result['exit_price']:.2f}
📈 Прибыль: {result['profit_pct']:.2f}% (${result['profit_usd']:.2f})
🔍 Причина: {result['reason']}

📊 Статистика:
• Всего сделок: {self.state_manager.state['total_trades']}
• Прибыльных: {self.state_manager.state['win_trades']}
• Общая прибыль: ${self.state_manager.state['total_profit']:.2f}
                    """
                    self.telegram_bot.send_message(message)
                    
        except Exception as e:
            logging.error(f"Error in position state: {e}")
    
    def _fetch_market_data(self, timeframe: str, limit: int = 100) -> pd.DataFrame:
        """Получение рыночных данных"""
        try:
            ohlcv = self.exchange_client.fetch_ohlcv(TradingConfig.SYMBOL, timeframe, limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df
            
        except Exception as e:
            logging.error(f"Failed to fetch {timeframe} data: {e}")
            return None
    
    def _get_ml_prediction(self, df: pd.DataFrame, market_condition: MarketCondition) -> tuple:
        """Получение ML предсказания"""
        try:
            if len(df) < 20:
                return 0.5, 0.5
            
            # Подготовка признаков для ML
            latest = df.iloc[-1]
            features = np.array([
                latest['rsi'],
                latest['macd'],
                latest['ema_cross'],
                latest['bb_position'],
                latest['stoch_k'],
                latest['adx'],
                latest['volume_ratio'],
                latest['close'] / latest['open'] - 1  # price change
            ])
            
            prediction, confidence = self.ml_model.predict(features, market_condition.value)
            return prediction, confidence
            
        except Exception as e:
            logging.error(f"ML prediction failed: {e}")
            return 0.5, 0.5
    
    def _update_rsi_counter(self, df: pd.DataFrame):
        """Обновление счетчика RSI >70"""
        try:
            latest_rsi = df['rsi'].iloc[-1]
            if latest_rsi > TradingConfig.RSI_OVERBOUGHT:
                self.rsi_over_70_candles += 1
            else:
                self.rsi_over_70_candles = 0
                
        except Exception as e:
            logging.error(f"Failed to update RSI counter: {e}")
    
    def reevaluate_market(self):
        """Переоценка рыночных условий"""
        try:
            logging.info("🔄 Market reevaluation started...")
            
            # Здесь можно добавить логику переобучения ML модели
            # self.retrain_ml_model()
            
            self.last_market_reevaluation = datetime.now()
            logging.info("✅ Market reevaluation completed")
            
        except Exception as e:
            logging.error(f"Market reevaluation failed: {e}")


if __name__ == "__main__":
    # Создание необходимых директорий
    os.makedirs("models", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    # Запуск бота
    bot = TradingBot()
    bot.run()
