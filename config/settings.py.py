import os
from dataclasses import dataclass
from enum import Enum

@dataclass
class TradingConfig:
    """Централизованная конфигурация торгового бота"""
    # Основные параметры
    SYMBOL = "BTC/USDT"
    POSITION_SIZE_USD = float(os.getenv('TRADE_AMOUNT', 50.0))
    
    # Параметры риск-менеджмента
    TAKE_PROFIT_PCT = 1.5
    STOP_LOSS_PCT = 2.0
    
    # Параметры RSI
    RSI_OVERBOUGHT = 70
    RSI_CRITICAL = 90
    RSI_CLOSE_CANDLES = 5
    
    # Адаптация к рынку
    BULL_MARKET_MODIFIER = -0.20
    BEAR_MARKET_MODIFIER = 0.40
    OVERHEATED_MODIFIER = 0.30
    
    # Временные параметры
    ANALYSIS_INTERVAL = 15  # минут
    MARKET_REEVALUATION = 4  # часа
    POST_SALE_COOLDOWN = 60  # минут
    VOLATILITY_THRESHOLD = 5.0
    
    # Минимальный балл для входа
    MIN_SCORE_TO_BUY = 3
    
    # API ключи
    GATE_API_KEY = os.getenv('GATE_API_KEY')
    GATE_API_SECRET = os.getenv('GATE_API_SECRET')
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    CHAT_ID = os.getenv('CHAT_ID')

class MarketCondition(Enum):
    STRONG_BULL = "strong_bull"
    WEAK_BULL = "weak_bull"
    SIDEWAYS = "sideways"
    WEAK_BEAR = "weak_bear"
    STRONG_BEAR = "strong_bear"

class TradingState(Enum):
    WAITING = "waiting"
    IN_POSITION = "in_position"
    COOLDOWN = "cooldown"