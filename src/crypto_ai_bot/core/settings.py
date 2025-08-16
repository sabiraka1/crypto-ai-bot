from __future__ import annotations
import os, json
from decimal import Decimal
from typing import Dict, Any

class Settings:
    # --- Core modes & trading ---
    MODE: str
    ENABLE_TRADING: bool
    SYMBOL: str
    TIMEFRAME: str
    DEFAULT_ORDER_SIZE: Decimal
    MAX_ORDER_SIZE: Decimal

    # --- Storage ---
    DB_PATH: str

    # --- Timing ---
    TIME_DRIFT_MAX_MS: int

    # --- Telegram (optional) ---
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_SECRET_TOKEN: str

    # --- Decision weights ---
    SCORE_RULE_WEIGHT: float
    SCORE_AI_WEIGHT: float
    THRESHOLD_BUY: float
    THRESHOLD_SELL: float

    # --- Event bus backpressure (new) ---
    EVENT_BACKPRESSURE_MAP: Dict[str, str]

    def __init__(self) -> None:
        # Modes
        self.MODE = os.getenv("MODE", "paper").strip().lower()
        self.ENABLE_TRADING = os.getenv("ENABLE_TRADING", "false").strip().lower() == "true"

        # Market defaults
        self.SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
        self.TIMEFRAME = os.getenv("TIMEFRAME", "1h")

        # Sizes
        self.DEFAULT_ORDER_SIZE = Decimal(os.getenv("DEFAULT_ORDER_SIZE", "0"))
        self.MAX_ORDER_SIZE = Decimal(os.getenv("MAX_ORDER_SIZE", "0"))

        # Storage
        self.DB_PATH = os.getenv("DB_PATH", "data/bot.db")

        # Timing
        self.TIME_DRIFT_MAX_MS = int(os.getenv("TIME_DRIFT_MAX_MS", "1500"))

        # Telegram
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN", "")

        # Weights & thresholds
        self.SCORE_RULE_WEIGHT = float(os.getenv("SCORE_RULE_WEIGHT", "0.5"))
        self.SCORE_AI_WEIGHT = float(os.getenv("SCORE_AI_WEIGHT", "0.5"))
        s = self.SCORE_RULE_WEIGHT + self.SCORE_AI_WEIGHT
        if s <= 0:
            self.SCORE_RULE_WEIGHT = 0.5
            self.SCORE_AI_WEIGHT = 0.5
        else:
            self.SCORE_RULE_WEIGHT /= s
            self.SCORE_AI_WEIGHT /= s

        self.THRESHOLD_BUY = float(os.getenv("THRESHOLD_BUY", "0.6"))
        self.THRESHOLD_SELL = float(os.getenv("THRESHOLD_SELL", "0.4"))
        # sanitize
        self.THRESHOLD_BUY = min(max(self.THRESHOLD_BUY, 0.0), 1.0)
        self.THRESHOLD_SELL = min(max(self.THRESHOLD_SELL, 0.0), 1.0)

        # Backpressure map: JSON in ENV or defaults
        bp_json = os.getenv("EVENT_BACKPRESSURE_JSON", "").strip()
        default_map = {
            "orders.*": "keep_latest",
            "metrics.*": "drop_oldest",
            "audit.*": "block",
        }
        if bp_json:
            try:
                user = json.loads(bp_json)
                if isinstance(user, dict):
                    # whitelisted values
                    cleaned = {}
                    for k, v in user.items():
                        if str(v) in ("block", "drop_oldest", "keep_latest"):
                            cleaned[str(k)] = str(v)
                    if cleaned:
                        default_map.update(cleaned)
            except Exception:
                pass
        self.EVENT_BACKPRESSURE_MAP = default_map

    @classmethod
    def build(cls) -> "Settings":
        return cls()
