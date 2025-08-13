# src/crypto_ai_bot/config/settings.py
"""
✅ Unified Settings for crypto_ai_bot
- Единый dataclass Settings с @classmethod load()
- Полная совместимость с bot/position_manager/risk_manager/signals
- Поддержка Fusion/AI/ATR%/часы/папки/вебхук и т.д.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from enum import Enum


# ── Helpers ──────────────────────────────────────────────────────────────────
def getenv_bool(name: str, default: bool = False) -> bool:
    return str(os.getenv(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}

def getenv_int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def getenv_float(name: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def getenv_list(name: str, default: Optional[List[str]] = None, sep: str = ",") -> List[str]:
    val = os.getenv(name)
    if not val:
        return list(default) if default else []
    return [x.strip() for x in val.split(sep) if x.strip()]


# ── Optional enums (для удобства) ────────────────────────────────────────────
class MarketCondition(Enum):
    STRONG_BULL = "STRONG_BULL"
    WEAK_BULL   = "WEAK_BULL"
    SIDEWAYS    = "SIDEWAYS"
    WEAK_BEAR   = "WEAK_BEAR"
    STRONG_BEAR = "STRONG_BEAR"

class TradingState(Enum):
    WAITING     = "waiting"
    ANALYZING   = "analyzing"
    ENTERING    = "entering"
    IN_POSITION = "in_position"
    EXITING     = "exiting"
    COOLDOWN    = "cooldown"
    PAUSED      = "paused"


# ── Main Settings ────────────────────────────────────────────────────────────
@dataclass
class Settings:
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    CHAT_ID: str = os.getenv("CHAT_ID", "")
    ADMIN_CHAT_IDS: List[str] = field(default_factory=lambda: getenv_list("ADMIN_CHAT_IDS", []))
    TELEGRAM_SECRET_TOKEN: str = os.getenv("TELEGRAM_SECRET_TOKEN", "")

    # Gate.io API
    GATE_API_KEY: str = os.getenv("GATE_API_KEY", "")
    GATE_API_SECRET: str = os.getenv("GATE_API_SECRET", "")

    # Core
    PORT: int = getenv_int("PORT", 5000)
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    SAFE_MODE: bool = getenv_bool("SAFE_MODE", True)
    ENABLE_TRADING: bool = getenv_bool("ENABLE_TRADING", True)
    ENABLE_WEBHOOK: bool = getenv_bool("ENABLE_WEBHOOK", False)

    # Trading basics
    SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "15m")
    ANALYSIS_INTERVAL: int = getenv_int("ANALYSIS_INTERVAL", 15)  # минут
    ANALYSIS_TIMEFRAMES: List[str] = field(default_factory=lambda: getenv_list("ANALYSIS_TIMEFRAMES", ["15m", "1h", "4h"]))
    OHLCV_LIMIT: int = getenv_int("OHLCV_LIMIT", 200)

    # Sizing / risk caps
    POSITION_SIZE_USD: float = getenv_float("TRADE_AMOUNT", 100.0)  # базовая сумма сделки
    RISK_PER_TRADE: float = getenv_float("RISK_PER_TRADE", 0.02)    # 2% от эквити
    MAX_CONCURRENT_POS: int = getenv_int("MAX_CONCURRENT_POS", 2)
    DAILY_MAX_DRAWDOWN: float = getenv_float("DAILY_MAX_DRAWDOWN", 0.06)
    MIN_POSITION_SIZE: float = getenv_float("MIN_POSITION_SIZE", 10.0)
    MIN_VOLUME_RATIO: float = getenv_float("MIN_VOLUME_RATIO", 0.30)  # vol/vol_sma

    # AI / scoring
    MIN_SCORE_TO_BUY: float = getenv_float("MIN_SCORE_TO_BUY", 0.65)
    MIN_RULE_SCORE: float = getenv_float("MIN_RULE_SCORE", 0.0)
    MIN_AI_SCORE: float = getenv_float("MIN_AI_SCORE", 0.0)
    MAX_SCORE_DIVERGENCE: float = getenv_float("MAX_SCORE_DIVERGENCE", 0.5)

    AI_ENABLE: bool = getenv_bool("AI_ENABLE", False)
    AI_MIN_TO_TRADE: float = getenv_float("AI_MIN_TO_TRADE", 0.70)
    AI_FAILOVER_SCORE: float = getenv_float("AI_FAILOVER_SCORE", 0.55)
    ENFORCE_AI_GATE: bool = getenv_bool("ENFORCE_AI_GATE", True)

    # Fusion
    FUSION_STRATEGY: str = os.getenv("FUSION_STRATEGY", "adaptive")
    FUSION_ALPHA: float = getenv_float("FUSION_ALPHA", 0.6)
    FUSION_CONFLICT_THRESHOLD: float = getenv_float("FUSION_CONFLICT_THRESHOLD", 0.3)
    FUSION_CONSENSUS_THRESHOLD: float = getenv_float("FUSION_CONSENSUS_THRESHOLD", 0.6)

    # ATR / volatility (унифицировано с валидатором/entry/risk_manager)
    ATR_PERIOD: int = getenv_int("ATR_PERIOD", 14)
    RISK_ATR_METHOD: str = os.getenv("RISK_ATR_METHOD", "ewm").lower()  # "ewm"|"sma"
    RISK_ATR_COMPARE: bool = getenv_bool("RISK_ATR_COMPARE", False)

    ATR_PCT_MIN: float = getenv_float("ATR_PCT_MIN", 0.30)  # % от цены
    ATR_PCT_MAX: float = getenv_float("ATR_PCT_MAX", 10.00) # % от цены
    VOLATILITY_LOOKBACK: int = getenv_int("VOLATILITY_LOOKBACK", 20)
    VOLUME_LOOKBACK: int = getenv_int("VOLUME_LOOKBACK", 20)

    INFO_LOG_INTERVAL_SEC: int = getenv_int("INFO_LOG_INTERVAL_SEC", 300)

    # Time windows
    TRADING_HOUR_START: int = getenv_int("TRADING_HOUR_START", 0)   # 0..23 (UTC)
    TRADING_HOUR_END: int = getenv_int("TRADING_HOUR_END", 24)      # 1..24 (UTC)
    DISABLE_WEEKEND_TRADING: bool = getenv_bool("DISABLE_WEEKEND_TRADING", False)

    # SL/TP (entry policy / position manager)
    SL_ATR_MULTIPLIER: float = getenv_float("SL_ATR_MULTIPLIER", 2.0)
    TP_ATR_MULTIPLIER: float = getenv_float("TP_ATR_MULTIPLIER", 3.0)
    TRAILING_STOP_ENABLE: bool = getenv_bool("TRAILING_STOP_ENABLE", True)
    TRAILING_STOP_PCT: float = getenv_float("TRAILING_STOP_PCT", 0.5)  # 0.5%

    # Performance (опционально)
    MAX_CONSECUTIVE_LOSSES: int = getenv_int("MAX_CONSECUTIVE_LOSSES", 5)
    MAX_DRAWDOWN_PCT: float = getenv_float("MAX_DRAWDOWN_PCT", 15.0)
    MIN_WIN_RATE: float = getenv_float("MIN_WIN_RATE", 35.0)
    NEGATIVE_SHARPE_LIMIT: float = getenv_float("NEGATIVE_SHARPE_LIMIT", 0.0)
    POOR_RR_THRESHOLD: float = getenv_float("POOR_RR_THRESHOLD", 0.5)
    PERFORMANCE_ALERT_INTERVAL: int = getenv_int("PERFORMANCE_ALERT_INTERVAL", 300)

    # Paths
    DATA_DIR: str = os.getenv("DATA_DIR", "data")
    MODELS_DIR: str = os.getenv("MODELS_DIR", os.getenv("MODEL_DIR", "models"))
    LOGS_DIR: str = os.getenv("LOGS_DIR", "logs")
    CLOSED_TRADES_CSV: str = os.getenv("CLOSED_TRADES_CSV", os.path.join(DATA_DIR, "closed_trades.csv"))
    SIGNALS_CSV: str = os.getenv("SIGNALS_CSV", os.path.join(DATA_DIR, "signals_snapshots.csv"))

    # Webhook
    PUBLIC_URL: str = os.getenv("PUBLIC_URL", "")
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

    # Misc
    COMMAND_COOLDOWN: int = getenv_int("COMMAND_COOLDOWN", 3)

    # ---- methods ------------------------------------------------------------
    @classmethod
    def load(cls) -> "Settings":
        """
        Позволяет main.py вызывать Settings.load(). Можно подключить dotenv при желании.
        """
        cfg = cls()
        # безопасно создаём каталоги
        try:
            os.makedirs(os.path.dirname(cfg.CLOSED_TRADES_CSV) or ".", exist_ok=True)
            os.makedirs(os.path.dirname(cfg.SIGNALS_CSV) or ".", exist_ok=True)
            os.makedirs(cfg.LOGS_DIR or ".", exist_ok=True)
            os.makedirs(cfg.MODELS_DIR or ".", exist_ok=True)
        except Exception:
            pass
        return cfg

    # Вспомогательные сводки/валидации (по желанию)
    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.ANALYSIS_INTERVAL <= 0:
            errors.append("ANALYSIS_INTERVAL must be > 0")
        if not (0 <= self.MIN_SCORE_TO_BUY <= 1):
            errors.append("MIN_SCORE_TO_BUY must be in [0..1]")
        if not (0 < self.ATR_PERIOD <= 100):
            errors.append("ATR_PERIOD must be in (0..100]")
        if self.RISK_ATR_METHOD not in {"ewm", "sma"}:
            errors.append("RISK_ATR_METHOD must be 'ewm' or 'sma'")
        if not (0.0 < self.MIN_POSITION_SIZE):
            errors.append("MIN_POSITION_SIZE must be > 0")
        min_stop = getenv_float("MIN_STOP_PCT", 0.005)
        max_stop = getenv_float("MAX_STOP_PCT", 0.05)
        if not (0.0 < min_stop < max_stop <= 1.0):
            errors.append("Invalid SL boundaries: MIN_STOP_PCT..MAX_STOP_PCT")
        # Вебхук
        if self.ENABLE_WEBHOOK and not (self.PUBLIC_URL and self.WEBHOOK_SECRET):
            errors.append("ENABLE_WEBHOOK=1 but PUBLIC_URL/WEBHOOK_SECRET not set")
        return errors

    def get_atr_config(self) -> Dict[str, Any]:
        return {
            "period": self.ATR_PERIOD,
            "risk_method": self.RISK_ATR_METHOD,
            "compare_enabled": self.RISK_ATR_COMPARE,
            "log_interval": self.INFO_LOG_INTERVAL_SEC,
        }

    def get_risk_config(self) -> Dict[str, Any]:
        return {
            "atr_period": self.ATR_PERIOD,
            "atr_method": self.RISK_ATR_METHOD,
            "min_stop_pct": getenv_float("MIN_STOP_PCT", 0.005),
            "max_stop_pct": getenv_float("MAX_STOP_PCT", 0.05),
            "volatility_lookback": self.VOLATILITY_LOOKBACK,
            "volume_lookback": self.VOLUME_LOOKBACK,
        }

    def get_performance_thresholds(self) -> Dict[str, Any]:
        return {
            "max_consecutive_losses": self.MAX_CONSECUTIVE_LOSSES,
            "max_drawdown_pct": self.MAX_DRAWDOWN_PCT / 100.0,
            "min_win_rate": self.MIN_WIN_RATE / 100.0,
            "negative_sharpe_limit": self.NEGATIVE_SHARPE_LIMIT,
            "poor_rr_threshold": self.POOR_RR_THRESHOLD,
            "alert_interval": self.PERFORMANCE_ALERT_INTERVAL,
        }

    def summary(self) -> str:
        return (
            f"🔧 Config: {self.SYMBOL}@{self.TIMEFRAME} | SAFE={self.SAFE_MODE} | "
            f"MIN_SCORE={self.MIN_SCORE_TO_BUY} | AI={self.AI_ENABLE} | "
            f"ATR(period={self.ATR_PERIOD},{self.RISK_ATR_METHOD}) | "
            f"ATR%[{self.ATR_PCT_MIN}..{self.ATR_PCT_MAX}] | "
            f"FUSION={self.FUSION_STRATEGY}"
        )


# ── Backward compatibility (если где-то ожидался TradingConfig) ──────────────
TradingConfig = Settings


# ── Optional side-effects exports (если кто-то импортировал из старого файла) ─
_cfg = Settings.load()
CLOSED_TRADES_CSV = _cfg.CLOSED_TRADES_CSV
SIGNALS_CSV = _cfg.SIGNALS_CSV
MODELS_DIR = _cfg.MODELS_DIR
LOGS_DIR = _cfg.LOGS_DIR
INFO_LOG_INTERVAL_SEC = _cfg.INFO_LOG_INTERVAL_SEC
ATR_PERIOD = _cfg.ATR_PERIOD
RISK_ATR_METHOD = _cfg.RISK_ATR_METHOD
RISK_ATR_COMPARE = _cfg.RISK_ATR_COMPARE

__all__ = ["Settings", "TradingConfig"]
