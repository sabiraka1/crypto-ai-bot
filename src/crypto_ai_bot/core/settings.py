from __future__ import annotations
import os, json
from decimal import Decimal
from typing import Dict, Any, Optional

__all__ = ["Settings"]

def _b(s: Optional[str], *, default: bool = False) -> bool:
    if s is None:
        return default
    s = s.strip().lower()
    return s in ("1", "true", "yes", "y", "on")

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

class Settings:
    """
    Единственное место чтения ENV. Никаких побочных эффектов.
    """
    # ---- Конструктор читает ENV и нормализует значения ----
    def __init__(self) -> None:
        # ---------- Режимы/торговля ----------
        self.MODE: str = os.getenv("MODE", "paper").strip().lower()          # live | paper | backtest
        self.SAFE_MODE: bool = _b(os.getenv("SAFE_MODE"), default=False)     # при True запрещаем исполнение ордеров

        self.ENABLE_TRADING: bool = _b(os.getenv("ENABLE_TRADING"), default=False)
        if self.SAFE_MODE:
            self.ENABLE_TRADING = False

        # ---------- Рынок ----------
        self.SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT")
        self.TIMEFRAME: str = os.getenv("TIMEFRAME", "1h")

        self.DEFAULT_ORDER_SIZE: Decimal = Decimal(os.getenv("DEFAULT_ORDER_SIZE", "0"))
        self.MAX_ORDER_SIZE: Decimal = Decimal(os.getenv("MAX_ORDER_SIZE", "0"))

        # ---------- Хранилище ----------
        self.DB_PATH: str = os.getenv("DB_PATH", "data/bot.db")
        self.DB_PRAGMA_JOURNAL_MODE: str = os.getenv("DB_PRAGMA_JOURNAL_MODE", "WAL")
        # Пороги обслуживания SQLite
        self.DB_VACUUM_MB_THRESHOLD: float = float(os.getenv("DB_VACUUM_MB_THRESHOLD", "128"))  # VACUUM если файл > N МБ
        self.DB_ANALYZE_EVERY_N_CHANGES: int = int(os.getenv("DB_ANALYZE_EVERY_N_CHANGES", "50000"))

        # ---------- Тайминг ----------
        self.TIME_DRIFT_MAX_MS: int = int(os.getenv("TIME_DRIFT_MAX_MS", "1500"))
        self.TRADING_START_HOUR: int = int(os.getenv("TRADING_START_HOUR", "0"))
        self.TRADING_END_HOUR: int = int(os.getenv("TRADING_END_HOUR", "24"))
        if self.TRADING_START_HOUR < 0 or self.TRADING_START_HOUR > 23:
            self.TRADING_START_HOUR = 0
        if self.TRADING_END_HOUR < 1 or self.TRADING_END_HOUR > 24:
            self.TRADING_END_HOUR = 24

        # ---------- Telegram ----------
        self.TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_SECRET_TOKEN: str = os.getenv("TELEGRAM_SECRET_TOKEN", "")
        self.TELEGRAM_ENABLED: bool = _b(os.getenv("TELEGRAM_ENABLED"), default=False)

        # ---------- Весовые коэффициенты & пороги решений ----------
        self.SCORE_RULE_WEIGHT: float = float(os.getenv("SCORE_RULE_WEIGHT", "0.5"))
        self.SCORE_AI_WEIGHT: float = float(os.getenv("SCORE_AI_WEIGHT", "0.5"))
        s = self.SCORE_RULE_WEIGHT + self.SCORE_AI_WEIGHT
        if s <= 0:
            self.SCORE_RULE_WEIGHT, self.SCORE_AI_WEIGHT = 0.5, 0.5
        else:
            self.SCORE_RULE_WEIGHT /= s
            self.SCORE_AI_WEIGHT /= s

        self.THRESHOLD_BUY: float = _clamp(float(os.getenv("THRESHOLD_BUY", "0.6")), 0.0, 1.0)
        self.THRESHOLD_SELL: float = _clamp(float(os.getenv("THRESHOLD_SELL", "0.4")), 0.0, 1.0)

        # ---------- Ограничения риска ----------
        self.MAX_SPREAD_PCT: float = float(os.getenv("MAX_SPREAD_PCT", "0.30"))        # %
        self.MAX_DRAWDOWN_PCT: float = float(os.getenv("MAX_DRAWDOWN_PCT", "5.0"))     # %
        self.MAX_SEQ_LOSSES: int = int(os.getenv("MAX_SEQ_LOSSES", "5"))
        self.MAX_EXPOSURE_PCT: float = float(os.getenv("MAX_EXPOSURE_PCT", "100.0"))   # % от equity
        self.MAX_EXPOSURE_USD: Optional[float] = float(os.getenv("MAX_EXPOSURE_USD")) if os.getenv("MAX_EXPOSURE_USD") else None

        # ---------- Rate limits (для декораторов в use_cases) ----------
        self.RATE_LIMIT_EVAL_AND_EXECUTE_PER_MIN: int = int(os.getenv("RATE_LIMIT_EVAL_AND_EXECUTE_PER_MIN", "20"))
        self.RATE_BURST_EVAL_AND_EXECUTE: int = int(os.getenv("RATE_BURST_EVAL_AND_EXECUTE", "40"))
        self.RATE_LIMIT_PLACE_ORDER_PER_MIN: int = int(os.getenv("RATE_LIMIT_PLACE_ORDER_PER_MIN", "30"))
        self.RATE_BURST_PLACE_ORDER: int = int(os.getenv("RATE_BURST_PLACE_ORDER", "60"))

        # ---------- Брокер (live) ----------
        # Используется фабрикой create_broker() при MODE=live|paper
        self.EXCHANGE_ID: str = os.getenv("EXCHANGE_ID", "binance")
        self.API_KEY: str = os.getenv("API_KEY", "")
        self.API_SECRET: str = os.getenv("API_SECRET", "")
        self.API_PASSWORD: str = os.getenv("API_PASSWORD", "")  # для некоторых бирж (OKX/Bybit)

        # ---------- Backpressure для событий ----------
        bp_json = os.getenv("EVENT_BACKPRESSURE_JSON", "").strip()
        default_map: Dict[str, str] = {
            "orders.*": "keep_latest",
            "metrics.*": "drop_oldest",
            "audit.*": "block",
        }
        if bp_json:
            try:
                user = json.loads(bp_json)
                if isinstance(user, dict):
                    cleaned = {}
                    for k, v in user.items():
                        sv = str(v)
                        if sv in ("block", "drop_oldest", "keep_latest"):
                            cleaned[str(k)] = sv
                    if cleaned:
                        default_map.update(cleaned)
            except Exception:
                pass
        self.EVENT_BACKPRESSURE_MAP: Dict[str, str] = default_map

    # ---------- Фабрика ----------
    @classmethod
    def build(cls) -> "Settings":
        return cls()
