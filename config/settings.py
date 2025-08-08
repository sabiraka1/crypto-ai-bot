import os
from dataclasses import dataclass
from enum import Enum

@dataclass
class TradingConfig:
    """Централизованная конфигурация торгового бота"""

    # Основные параметры
    SYMBOL: str = "BTC/USDT"
    POSITION_SIZE_USD: float = float(os.getenv('TRADE_AMOUNT', 50.0))

    # Параметры риск-менеджмента (процентные предохранители)
    TAKE_PROFIT_PCT: float = 1.5   # +1.5% (сетевой TP предохранитель)
    STOP_LOSS_PCT: float = 2.0     # -2.0% (сетевой SL предохранитель)

    # Параметры RSI
    RSI_OVERBOUGHT: int = 70
    RSI_CRITICAL: int = 90
    RSI_CLOSE_CANDLES: int = 5

    # Адаптация к рынку (модификаторы к порогу)
    BULL_MARKET_MODIFIER: float = -0.20
    BEAR_MARKET_MODIFIER: float = 0.40
    OVERHEATED_MODIFIER: float = 0.30

    # Временные параметры
    ANALYSIS_INTERVAL: int = 15   # минут
    MARKET_REEVALUATION: int = 4  # часа
    POST_SALE_COOLDOWN: int = 60  # минут
    VOLATILITY_THRESHOLD: float = 5.0

    # Минимальный балл для входа (теперь из .env; по умолчанию 2.0 вместо 3)
    # Это ближе к нашей «0.55»-логике на балльной шкале твоего скоринга.
    MIN_SCORE_TO_BUY: float = float(os.getenv('MIN_SCORE_TO_BUY', '2.0'))

    # API ключи
    GATE_API_KEY: str | None = os.getenv('GATE_API_KEY')
    GATE_API_SECRET: str | None = os.getenv('GATE_API_SECRET')
    BOT_TOKEN: str | None = os.getenv('BOT_TOKEN')
    CHAT_ID: str | None = os.getenv('CHAT_ID')

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
