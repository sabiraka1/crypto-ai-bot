from __future__ import annotations

import os
from decimal import Decimal

class Settings:
    # --- mode ---
    MODE: str
    PAPER_MODE: bool

    # --- symbols/time ---
    SYMBOL: str
    TIMEFRAME: str
    TIME_DRIFT_MAX_MS: int

    # --- risk ---
    MAX_SPREAD_PCT: float
    MAX_DRAWDOWN_PCT: float
    MAX_SEQ_LOSSES: int
    MAX_EXPOSURE_PCT: float | None
    MAX_EXPOSURE_USD: float | None
    TRADING_START_HOUR: int
    TRADING_END_HOUR: int

    # --- decision thresholds/weights ---
    THRESHOLD_BUY: float
    THRESHOLD_SELL: float
    SCORE_RULE_WEIGHT: float
    SCORE_AI_WEIGHT: float
    # backward-compat
    DECISION_RULE_WEIGHT: float
    DECISION_AI_WEIGHT: float

    DEFAULT_ORDER_SIZE: str

    # --- storage ---
    DB_PATH: str

    # --- telegram ---
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_SECRET_TOKEN: str

    # --- safety ---
    SAFE_MODE: bool

    # --- optional hints ---
    ACCOUNT_EQUITY_USD: float | None

    @classmethod
    def build(cls) -> "Settings":
        self = cls()
        env = os.getenv

        self.MODE = env("MODE", "paper").strip().lower()
        self.PAPER_MODE = self.MODE == "paper"

        self.SYMBOL = env("SYMBOL", "BTC/USDT")
        self.TIMEFRAME = env("TIMEFRAME", "1h")
        self.TIME_DRIFT_MAX_MS = int(env("TIME_DRIFT_MAX_MS", "1500"))

        # Risk
        self.MAX_SPREAD_PCT = float(env("MAX_SPREAD_PCT", "0.25"))
        self.MAX_DRAWDOWN_PCT = float(env("MAX_DRAWDOWN_PCT", "5.0"))
        self.MAX_SEQ_LOSSES = int(env("MAX_SEQ_LOSSES", "3"))
        self.MAX_EXPOSURE_PCT = float(env("MAX_EXPOSURE_PCT", "")) if env("MAX_EXPOSURE_PCT") else None
        self.MAX_EXPOSURE_USD = float(env("MAX_EXPOSURE_USD", "")) if env("MAX_EXPOSURE_USD") else None
        self.TRADING_START_HOUR = int(env("TRADING_START_HOUR", "0"))
        self.TRADING_END_HOUR = int(env("TRADING_END_HOUR", "24"))

        # Decision thresholds
        self.THRESHOLD_BUY = float(env("THRESHOLD_BUY", "0.60"))
        self.THRESHOLD_SELL = float(env("THRESHOLD_SELL", "0.40"))

        # Weights (harmonized)
        # accept both SCORE_* and DECISION_* names; SCORE_* take precedence
        score_rule = env("SCORE_RULE_WEIGHT")
        score_ai = env("SCORE_AI_WEIGHT")
        dec_rule = env("DECISION_RULE_WEIGHT")
        dec_ai = env("DECISION_AI_WEIGHT")

        self.SCORE_RULE_WEIGHT = float(score_rule) if score_rule else (float(dec_rule) if dec_rule else 0.5)
        self.SCORE_AI_WEIGHT   = float(score_ai)   if score_ai   else (float(dec_ai)   if dec_ai   else 0.5)

        # keep backward-compatible mirrors
        self.DECISION_RULE_WEIGHT = self.SCORE_RULE_WEIGHT
        self.DECISION_AI_WEIGHT   = self.SCORE_AI_WEIGHT

        self.DEFAULT_ORDER_SIZE = env("DEFAULT_ORDER_SIZE", "0.0")

        # Storage
        self.DB_PATH = env("DB_PATH", "data/bot.sqlite")

        # Telegram
        self.TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_SECRET_TOKEN = env("TELEGRAM_SECRET_TOKEN", "")

        # Safety
        self.SAFE_MODE = env("SAFE_MODE", "true").lower() in ("1","true","yes","on")

        # Optional hints
        self.ACCOUNT_EQUITY_USD = float(env("ACCOUNT_EQUITY_USD", "")) if env("ACCOUNT_EQUITY_USD") else None

        return self
