# src/crypto_ai_bot/core/domain/strategies/__init__.py
from __future__ import annotations

# Базовые контракты/типы
from .base import BaseStrategy, StrategyContext, MarketData

# Стратегии
from .ema_cross import EmaCrossStrategy
from .rsi_momentum import RSIMomentumStrategy
from .bollinger_bands import BollingerBandsStrategy
from .ema_atr import EmaAtrStrategy
from .signals_policy_strategy import SignalsPolicyStrategy

# Менеджер
from .manager import StrategyManager

# Позиционирование / выходы
from .position_sizing import (
    SizeConstraints,
    fixed_quote_amount,
    fixed_fractional,
    naive_kelly,
)
from .exit_policies import (
    StopLossPolicy,
    TakeProfitPolicy,
    TrailingStopPolicy,
)

__all__ = [
    "BaseStrategy",
    "StrategyContext",
    "MarketData",
    "EmaCrossStrategy",
    "RSIMomentumStrategy",
    "BollingerBandsStrategy",
    "EmaAtrStrategy",
    "SignalsPolicyStrategy",
    "StrategyManager",
    "SizeConstraints",
    "fixed_quote_amount",
    "fixed_fractional",
    "naive_kelly",
    "StopLossPolicy",
    "TakeProfitPolicy",
    "TrailingStopPolicy",
]
