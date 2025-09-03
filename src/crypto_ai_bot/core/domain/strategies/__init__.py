# src/crypto_ai_bot/core/domain/strategies/__init__.py
from __future__ import annotations

# ДћвЂДћВ°ДћВ·ДћВѕДћВІГ‘вЂ№ДћВµ ДћВєДћВѕДћВЅГ‘вЂљГ‘в‚¬ДћВ°ДћВєГ‘вЂљГ‘вЂ№/Г‘вЂљДћВёДћВїГ‘вЂ№
from .base import BaseStrategy, Decision, MarketData, StrategyContext
from .bollinger_bands import BollingerBandsStrategy
from .ema_atr import EmaAtrConfig, EmaAtrStrategy

# ДћВЎГ‘вЂљГ‘в‚¬ДћВ°Г‘вЂљДћВµДћВіДћВёДћВё
from .ema_cross import EmaCrossStrategy
from .exit_policies import (
    StopLossPolicy,
    TakeProfitPolicy,
    TrailingStopPolicy,
)

# ДћЕёДћВѕДћВ·ДћВёГ‘вЂ ДћВёДћВѕДћВЅДћВёГ‘в‚¬ДћВѕДћВІДћВ°ДћВЅДћВёДћВµ / ДћВІГ‘вЂ№Г‘вЂ¦ДћВѕДћВґГ‘вЂ№
from .position_sizing import (
    SizeConstraints,
    fixed_fractional,
    fixed_quote_amount,
    naive_kelly,
)
from .rsi_momentum import RSIMomentumStrategy
from .signals_policy_strategy import SignalsPolicyStrategy

# ДћЕ“ДћВµДћВЅДћВµДћВґДћВ¶ДћВµГ‘в‚¬ - ДћВёГ‘ВЃДћВїГ‘в‚¬ДћВ°ДћВІДћВ»ДћВµДћВЅДћВѕ: ДћВёДћВјДћВїДћВѕГ‘в‚¬Г‘вЂљ ДћВёДћВ· strategy_manager
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
