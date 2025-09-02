# src/crypto_ai_bot/core/domain/strategies/__init__.py
from __future__ import annotations

# Базовые контракты/типы
from .base import BaseStrategy, Decision, MarketData, StrategyContext
from .bollinger_bands import BollingerBandsStrategy
from .ema_atr import EmaAtrConfig, EmaAtrStrategy

# Стратегии
from .ema_cross import EmaCrossStrategy
from .exit_policies import (
    StopLossPolicy,
    TakeProfitPolicy,
    TrailingStopPolicy,
)

# Менеджер - исправлено: импорт из strategy_manager
from .strategy_manager import StrategyManager

# Позиционирование / выходы
from .position_sizing import (
    SizeConstraints,
    fixed_fractional,
    fixed_quote_amount,
    naive_kelly,
)
from .rsi_momentum import RSIMomentumStrategy
from .signals_policy_strategy import SignalsPolicyStrategy

__all__ = [
    "BaseStrategy",
    "BollingerBandsStrategy",
    "Decision",
    "EmaAtrConfig",
    "EmaAtrStrategy",
    "EmaCrossStrategy",
    "MarketData",
    "RSIMomentumStrategy",
    "SignalsPolicyStrategy",
    "SizeConstraints",
    "StopLossPolicy",
    "StrategyContext",
    "StrategyManager",
    "TakeProfitPolicy",
    "TrailingStopPolicy",
    "fixed_fractional",
    "fixed_quote_amount",
    "naive_kelly",
]