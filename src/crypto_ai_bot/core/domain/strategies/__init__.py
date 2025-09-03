# src/crypto_ai_bot/core/domain/strategies/__init__.py
from __future__ import annotations

# Ğ‘Ğ°Ğ·Ğ¾Ğ²Ñ‹Ğµ ĞºĞ¾Ğ½Ñ‚Ñ€Ğ°ĞºÑ‚Ñ‹/Ñ‚Ğ¸Ğ¿Ñ‹
from .base import BaseStrategy, Decision, MarketData, StrategyContext
from .bollinger_bands import BollingerBandsStrategy
from .ema_atr import EmaAtrConfig, EmaAtrStrategy

# Ğ¡Ñ‚Ñ€Ğ°Ñ‚ĞµĞ³Ğ¸Ğ¸
from .ema_cross import EmaCrossStrategy
from .exit_policies import (
    StopLossPolicy,
    TakeProfitPolicy,
    TrailingStopPolicy,
)

# ĞŸĞ¾Ğ·Ğ¸Ñ†Ğ¸Ğ¾Ğ½Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ¸Ğµ / Ğ²Ñ‹Ñ…Ğ¾Ğ´Ñ‹
from .position_sizing import (
    SizeConstraints,
    fixed_fractional,
    fixed_quote_amount,
    naive_kelly,
)
from .rsi_momentum import RSIMomentumStrategy
from .signals_policy_strategy import SignalsPolicyStrategy

# ĞœĞµĞ½ĞµĞ´Ğ¶ĞµÑ€ - Ğ¸ÑĞ¿Ñ€Ğ°Ğ²Ğ»ĞµĞ½Ğ¾: Ğ¸Ğ¼Ğ¿Ğ¾Ñ€Ñ‚ Ğ¸Ğ· strategy_manager
from .strategy_manager import StrategyManager

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
