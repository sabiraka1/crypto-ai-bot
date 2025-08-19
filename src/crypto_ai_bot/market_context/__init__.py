# src/crypto_ai_bot/market_context/__init__.py
"""
Модуль контекста рынка.
Предоставляет типы данных и функции для работы с рыночными данными.
"""
from typing import TypedDict, NotRequired, Dict, Any

from .snapshot import build_snapshot  # re-export для удобства


class OHLCV(TypedDict):
    """Структура данных OHLCV (Open, High, Low, Close, Volume)."""
    ts_ms: float
    open: float
    high: float
    low: float
    close: float
    volume: NotRequired[float]


class MarketContext(TypedDict, total=False):
    """Контекст рыночных данных с индикаторами и весами."""
    ts_ms: int
    sources: Dict[str, Any]
    indicators: Dict[str, float]
    weights: Dict[str, float]
    composite: float
    regime: str