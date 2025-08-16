from __future__ import annotations

import os
from decimal import Decimal

def _getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)

def _getenv_bool(name: str, default: bool=False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

def _getenv_int(name: str, default: int=0) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _getenv_float(name: str, default: float=0.0) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

class Settings:
    # Mode
    MODE: str
    SYMBOL: str
    TIMEFRAME: str

    # Paths
    DB_PATH: str

    # Decisions
    THRESHOLD_BUY: float
    THRESHOLD_SELL: float
    SCORE_RULE_WEIGHT: float
    SCORE_AI_WEIGHT: float
    DEFAULT_ORDER_SIZE: str

    # Risk
    MAX_SPREAD_PCT: float
    MAX_DRAWDOWN_PCT: float
    MAX_SEQ_LOSSES: int
    MAX_EXPOSURE_PCT: float | None
    MAX_EXPOSURE_USD: float | None
    TIME_DRIFT_MAX_MS: int
    TRADING_START_HOUR: int
    TRADING_END_HOUR: int

    # Rate limits
    RL_EVALUATE_CALLS: int
    RL_EVALUATE_PERIOD: float
    RL_PLACE_ORDER_CALLS: int
    RL_PLACE_ORDER_PERIOD: float
    RL_EVAL_EXEC_CALLS: int
    RL_EVAL_EXEC_PERIOD: float

    # DB maintenance
    DB_MAINTENANCE_ENABLE: bool
    DB_MAINTENANCE_INTERVAL_SEC: int
    DB_VACUUM_MIN_MB: float
    DB_VACUUM_FREE_RATIO: float
    DB_ANALYZE_EVERY_WRITES: int
    DB_WRITES_SINCE_ANALYZE: int  # счётчик; можно инкрементировать из репозиториев

    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_SECRET_TOKEN: str | None

    @classmethod
    def build(cls) -> "Settings":
        s = cls()
        s.MODE = _getenv("MODE", "paper")
        s.SYMBOL = _getenv("SYMBOL", "BTC/USDT")
        s.TIMEFRAME = _getenv("TIMEFRAME", "1h")

        s.DB_PATH = _getenv("DB_PATH", os.path.join("data", "bot.db"))

        s.THRESHOLD_BUY = _getenv_float("THRESHOLD_BUY", 0.60)
        s.THRESHOLD_SELL = _getenv_float("THRESHOLD_SELL", 0.40)
        s.SCORE_RULE_WEIGHT = _getenv_float("SCORE_RULE_WEIGHT", 0.5)
        s.SCORE_AI_WEIGHT = _getenv_float("SCORE_AI_WEIGHT", 0.5)
        s.DEFAULT_ORDER_SIZE = _getenv("DEFAULT_ORDER_SIZE", "0.0")

        s.MAX_SPREAD_PCT = _getenv_float("MAX_SPREAD_PCT", 0.25)
        s.MAX_DRAWDOWN_PCT = _getenv_float("MAX_DRAWDOWN_PCT", 5.0)
        s.MAX_SEQ_LOSSES = _getenv_int("MAX_SEQ_LOSSES", 3)
        s.MAX_EXPOSURE_PCT = _getenv_float("MAX_EXPOSURE_PCT", 0.0) or None
        s.MAX_EXPOSURE_USD = _getenv_float("MAX_EXPOSURE_USD", 0.0) or None
        s.TIME_DRIFT_MAX_MS = _getenv_int("TIME_DRIFT_MAX_MS", 1500)
        s.TRADING_START_HOUR = _getenv_int("TRADING_START_HOUR", 0)
        s.TRADING_END_HOUR = _getenv_int("TRADING_END_HOUR", 24)

        s.RL_EVALUATE_CALLS = _getenv_int("RL_EVALUATE_CALLS", 6)
        s.RL_EVALUATE_PERIOD = _getenv_float("RL_EVALUATE_PERIOD", 10)
        s.RL_PLACE_ORDER_CALLS = _getenv_int("RL_PLACE_ORDER_CALLS", 3)
        s.RL_PLACE_ORDER_PERIOD = _getenv_float("RL_PLACE_ORDER_PERIOD", 10)
        s.RL_EVAL_EXEC_CALLS = _getenv_int("RL_EVAL_EXEC_CALLS", 3)
        s.RL_EVAL_EXEC_PERIOD = _getenv_float("RL_EVAL_EXEC_PERIOD", 10)

        s.DB_MAINTENANCE_ENABLE = _getenv_bool("DB_MAINTENANCE_ENABLE", True)
        s.DB_MAINTENANCE_INTERVAL_SEC = _getenv_int("DB_MAINTENANCE_INTERVAL_SEC", 900)
        s.DB_VACUUM_MIN_MB = _getenv_float("DB_VACUUM_MIN_MB", 64)
        s.DB_VACUUM_FREE_RATIO = _getenv_float("DB_VACUUM_FREE_RATIO", 0.20)
        s.DB_ANALYZE_EVERY_WRITES = _getenv_int("DB_ANALYZE_EVERY_WRITES", 5000)
        s.DB_WRITES_SINCE_ANALYZE = 0  # инициализация счётчика

        s.TELEGRAM_BOT_TOKEN = _getenv("TELEGRAM_BOT_TOKEN", "")
        s.TELEGRAM_SECRET_TOKEN = _getenv("TELEGRAM_SECRET_TOKEN", "") or None

        return s
