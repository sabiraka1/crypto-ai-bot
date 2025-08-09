# config/settings.py

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------- helpers ----------
def getenv_bool(name: str, default: bool = False) -> bool:
    v = str(os.getenv(name, "")).strip().lower()
    if v == "":
        return bool(default)
    return v in ("1", "true", "yes", "on", "y")

def getenv_float(name: str, default: float) -> float:
    try:
        v = os.getenv(name, None)
        return float(v) if v is not None and str(v).strip() != "" else float(default)
    except Exception:
        return float(default)

def getenv_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name, None)
        return int(v) if v is not None and str(v).strip() != "" else int(default)
    except Exception:
        return int(default)


# ---------- enums ----------
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


# ---------- config ----------
@dataclass
class TradingConfig:
    """
    Централизованная конфигурация торгового бота.
    Все значения можно переопределить через переменные окружения.
    """

    # Основные параметры
    SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT")
    POSITION_SIZE_USD: float = getenv_float("TRADE_AMOUNT", 50.0)

    # Риск-менеджмент (процентные предохранители, в %)
    TAKE_PROFIT_PCT: float = getenv_float("TAKE_PROFIT_PCT", 1.5)   # +1.5%
    STOP_LOSS_PCT: float = getenv_float("STOP_LOSS_PCT", 2.0)       # -2.0%
    # (исправлена потенциальная опечатка STOP_LOСС_PCT с русской 'С' — игнорируется)

    # RSI
    RSI_OVERBOUGHT: int = getenv_int("RSI_OVERBOUGHT", 70)
    RSI_CRITICAL: int = getenv_int("RSI_CRITICAL", 90)
    RSI_CLOSE_CANDLES: int = getenv_int("RSI_CLOSE_CANDLES", 5)

    # Адаптация к рынку (модификаторы к порогу Buy Score; могут быть отрицательными/положительными)
    BULL_MARKET_MODIFIER: float = getenv_float("BULL_MARKET_MODIFIER", -0.20)
    BEAR_MARKET_MODIFIER: float = getenv_float("BEAR_MARKET_MODIFIER", 0.40)
    OVERHEATED_MODIFIER: float = getenv_float("OVERHEATED_MODIFIER", 0.30)

    # Временные параметры
    ANALYSIS_INTERVAL: int = getenv_int("ANALYSIS_INTERVAL", 15)    # минут
    MARKET_REEVALUATION: int = getenv_int("MARKET_REEVALUATION", 4) # часов
    POST_SALE_COOLDOWN: int = getenv_int("POST_SALE_COOLDOWN", 60) # минут
    VOLATILITY_THRESHOLD: float = getenv_float("VOLATILITY_THRESHOLD", 5.0)

    # Минимальный балл для входа в НОРМАЛИЗОВАННОЙ шкале [0..1]
    # Совместимо с новым ScoringEngine (buy_score_norm).
    MIN_SCORE_TO_BUY: float = getenv_float("MIN_SCORE_TO_BUY", 0.65)

    # API ключи/токены
    GATE_API_KEY: Optional[str] = os.getenv("GATE_API_KEY")
    GATE_API_SECRET: Optional[str] = os.getenv("GATE_API_SECRET")
    BOT_TOKEN: Optional[str] = os.getenv("BOT_TOKEN")
    CHAT_ID: Optional[str] = os.getenv("CHAT_ID")

    # Флаги
    SAFE_MODE: bool = getenv_bool("SAFE_MODE", False)           # paper-trading в ExchangeClient
    AI_ENABLE: bool = getenv_bool("AI_ENABLE", True)
