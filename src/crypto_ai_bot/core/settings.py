from __future__ import annotations
import os
from decimal import Decimal

class Settings:
    # --- Modes & toggles ---
    MODE: str
    ENABLE_TRADING: bool

    # --- Trading params ---
    SYMBOL: str
    TIMEFRAME: str
    DEFAULT_ORDER_SIZE: Decimal
    MAX_ORDER_SIZE: Decimal

    # --- Scoring weights ---
    SCORE_RULE_WEIGHT: float
    SCORE_AI_WEIGHT: float
    THRESHOLD_BUY: float
    THRESHOLD_SELL: float

    # --- Risk / time sync ---
    TIME_DRIFT_MAX_MS: int

    # --- Storage ---
    DB_PATH: str

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str | None
    TELEGRAM_SECRET_TOKEN: str | None

    @staticmethod
    def _get_bool(name: str, default: bool=False) -> bool:
        v = os.getenv(name)
        if v is None:
            return default
        return str(v).strip().lower() in {"1","true","yes","on"}

    @classmethod
    def build(cls) -> "Settings":
        self = cls()

        # Modes
        self.MODE = os.getenv("MODE", "paper").strip()
        self.ENABLE_TRADING = cls._get_bool("ENABLE_TRADING", False)

        # Trading
        self.SYMBOL = os.getenv("SYMBOL", "BTC/USDT").strip()
        self.TIMEFRAME = os.getenv("TIMEFRAME", "1h").strip()
        self.DEFAULT_ORDER_SIZE = Decimal(os.getenv("DEFAULT_ORDER_SIZE", "0.01"))
        self.MAX_ORDER_SIZE = Decimal(os.getenv("MAX_ORDER_SIZE", "10"))

        # Weights & thresholds
        self.SCORE_RULE_WEIGHT = float(os.getenv("SCORE_RULE_WEIGHT", "0.5"))
        self.SCORE_AI_WEIGHT   = float(os.getenv("SCORE_AI_WEIGHT", "0.5"))
        total = self.SCORE_RULE_WEIGHT + self.SCORE_AI_WEIGHT
        if total <= 0:
            raise ValueError("SCORE_RULE_WEIGHT + SCORE_AI_WEIGHT must be > 0")
        # normalize to 1.0 if not exact
        if abs(total - 1.0) > 1e-9:
            self.SCORE_RULE_WEIGHT /= total
            self.SCORE_AI_WEIGHT   /= total

        self.THRESHOLD_BUY  = float(os.getenv("THRESHOLD_BUY", "0.55"))
        self.THRESHOLD_SELL = float(os.getenv("THRESHOLD_SELL", "0.45"))
        if not 0 <= self.THRESHOLD_SELL <= self.THRESHOLD_BUY <= 1:
            # keep sane defaults
            self.THRESHOLD_BUY, self.THRESHOLD_SELL = 0.55, 0.45

        # Risk
        self.TIME_DRIFT_MAX_MS = int(os.getenv("TIME_DRIFT_MAX_MS", "1500"))

        # Storage
        self.DB_PATH = os.getenv("DB_PATH", "data/bot.db")

        # Telegram
        self.TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
        self.TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN")

        # Safe mode: in LIVE require explicit enable
        if self.MODE == "live" and not self.ENABLE_TRADING:
            # explicitly off unless ENABLE_TRADING=true
            pass

        return self
