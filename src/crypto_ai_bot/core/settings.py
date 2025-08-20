# src/crypto_ai_bot/core/settings.py
from __future__ import annotations

import os
from typing import Optional


def _getenv_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}

def _getenv_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return float(default)

def _getenv_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return int(default)


class Settings:
    """
    Единый источник конфигурации. Читает только из ENV.
    Никаких прямых os.environ за пределами этого модуля (см. архитектурные правила).
    """

    # --- режимы и актив ---
    MODE: str                         # "paper" | "live"
    SYMBOL: str                       # например, "BTC/USDT"
    TIMEFRAME: str                    # например, "15m"
    EXCHANGE: str                     # "gateio" (по умолчанию), "binance" и т.п.

    # --- торговая логика / фьюжн ---
    BUY_TH: float
    SELL_TH: float
    RSI_PERIOD: int
    MA_TREND_PERIOD: int
    FUSION_W_RSI: float
    FUSION_W_MOM: float
    FUSION_W_TREND: float

    # --- исполнение / рынок ---
    SLIPPAGE_BPS: float
    MAX_SPREAD_BPS: float

    # --- риски ---
    MAX_POSITIONS: int
    RISK_MAX_DRAWDOWN_PCT: float
    RISK_MAX_LOSSES: int
    RISK_HOURS_UTC: str  # строка с часами/днями (если используешь), иначе игнор

    # --- идемпотентность ---
    IDEMPOTENCY_TTL_SEC: int

    # --- gate/ccxt / лимиты и CB ---
    CCXT_ENABLE_RATE_LIMIT: bool
    ORDERS_RPS: int
    MARKET_DATA_RPS: int
    ACCOUNT_RPS: int

    CB_FAIL_THRESHOLD: int
    CB_OPEN_TIMEOUT_SEC: float
    CB_HALF_OPEN_CALLS: int
    CB_WINDOW_SEC: float

    # --- БД / файлы ---
    DB_PATH: str  # для SQLite
    DB_JOURNAL_MODE_WAL: bool

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: Optional[str]
    TELEGRAM_BOT_SECRET: Optional[str]          # секрет вебхука/подписи
    TELEGRAM_ALERT_CHAT_ID: Optional[str]       # целевой чат для алёртов (int строкой)

    # --- прочее ---
    ENABLE_TRADING: bool

    def __init__(self) -> None:
        # режим/актив
        self.MODE = os.getenv("MODE", "paper")
        self.SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
        self.TIMEFRAME = os.getenv("TIMEFRAME", "15m")
        self.EXCHANGE = os.getenv("EXCHANGE", "gateio").lower()

        # фьюжн/пороговые
        self.BUY_TH = _getenv_float("BUY_TH", 0.60)
        self.SELL_TH = _getenv_float("SELL_TH", -0.60)
        self.RSI_PERIOD = _getenv_int("RSI_PERIOD", 14)
        self.MA_TREND_PERIOD = _getenv_int("MA_TREND_PERIOD", 20)
        self.FUSION_W_RSI = _getenv_float("FUSION_W_RSI", 0.30)
        self.FUSION_W_MOM = _getenv_float("FUSION_W_MOM", 0.50)
        self.FUSION_W_TREND = _getenv_float("FUSION_W_TREND", 0.20)

        # исполнение
        self.SLIPPAGE_BPS = _getenv_float("SLIPPAGE_BPS", 20.0)   # 0.20%
        self.MAX_SPREAD_BPS = _getenv_float("MAX_SPREAD_BPS", 50.0)

        # риски
        self.MAX_POSITIONS = _getenv_int("MAX_POSITIONS", 1)
        self.RISK_MAX_DRAWDOWN_PCT = _getenv_float("RISK_MAX_DRAWDOWN_PCT", 10.0)
        self.RISK_MAX_LOSSES = _getenv_int("RISK_MAX_LOSSES", 3)
        self.RISK_HOURS_UTC = os.getenv("RISK_HOURS_UTC", "")  # пусто = 24/7

        # идемпотентность
        self.IDEMPOTENCY_TTL_SEC = _getenv_int("IDEMPOTENCY_TTL_SEC", 60)

        # лимиты/CB
        self.CCXT_ENABLE_RATE_LIMIT = _getenv_bool("CCXT_ENABLE_RATE_LIMIT", True)
        self.ORDERS_RPS = _getenv_int("ORDERS_RPS", 10)
        self.MARKET_DATA_RPS = _getenv_int("MARKET_DATA_RPS", 60)
        self.ACCOUNT_RPS = _getenv_int("ACCOUNT_RPS", 30)

        self.CB_FAIL_THRESHOLD = _getenv_int("CB_FAIL_THRESHOLD", 5)
        self.CB_OPEN_TIMEOUT_SEC = _getenv_float("CB_OPEN_TIMEOUT_SEC", 30.0)
        self.CB_HALF_OPEN_CALLS = _getenv_int("CB_HALF_OPEN_CALLS", 1)
        self.CB_WINDOW_SEC = _getenv_float("CB_WINDOW_SEC", 60.0)

        # БД
        self.DB_PATH = os.getenv("DB_PATH", "/data/bot.sqlite")
        self.DB_JOURNAL_MODE_WAL = _getenv_bool("DB_JOURNAL_MODE_WAL", True)

        # Telegram
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or None
        self.TELEGRAM_BOT_SECRET = os.getenv("TELEGRAM_BOT_SECRET") or None
        self.TELEGRAM_ALERT_CHAT_ID = os.getenv("TELEGRAM_ALERT_CHAT_ID") or None

        # прочее
        self.ENABLE_TRADING = _getenv_bool("ENABLE_TRADING", True)

        self._validate()

    # --- базовая валидация доменных инвариантов ---
    def _validate(self) -> None:
        if self.MAX_POSITIONS <= 0:
            raise ValueError("MAX_POSITIONS must be positive")
        if not isinstance(self.SYMBOL, str) or "/" not in self.SYMBOL:
            raise ValueError("SYMBOL must look like 'BASE/QUOTE', e.g. 'BTC/USDT'")
        if not (-1.0 <= self.SELL_TH < self.BUY_TH <= 1.0):
            raise ValueError("SELL_TH < BUY_TH must hold, both in [-1..1]")
        if not (0.0 < self.SLIPPAGE_BPS < 500.0):
            raise ValueError("SLIPPAGE_BPS looks invalid (0..500 expected)")
        if not (0.0 < self.MAX_SPREAD_BPS < 1000.0):
            raise ValueError("MAX_SPREAD_BPS looks invalid (0..1000 expected)")
        if self.MODE not in {"paper", "live"}:
            raise ValueError("MODE must be 'paper' or 'live'")

    # удобный фабричный метод
    @classmethod
    def load(cls) -> "Settings":
        return cls()
