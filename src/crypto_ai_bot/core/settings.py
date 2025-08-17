# src/crypto_ai_bot/core/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Tuple, Optional, List


@dataclass
class _DecisionProfile:
    name: str
    rule_weight: float
    ai_weight: float
    buy_threshold: float
    sell_threshold: float


class Settings:
    """
    Единственная точка чтения ENV и дефолтов.
    ВНИМАНИЕ: во всём проекте нельзя читать os.getenv вне этого файла.
    """

    # --- базовые режимы ---
    MODE: str = os.getenv("MODE", "paper").lower()  # live | paper | backtest
    SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "1h")
    LIMIT_BARS: int = int(os.getenv("LIMIT_BARS", "300"))
    ENABLE_TRADING: bool = os.getenv("ENABLE_TRADING", "false").lower() in {"1", "true", "yes"}
    SAFE_MODE: bool = os.getenv("SAFE_MODE", "true").lower() in {"1", "true", "yes"}

    # --- оркестратор ---
    TICK_PERIOD_SEC: int = int(os.getenv("TICK_PERIOD_SEC", "60"))
    METRICS_REFRESH_SEC: int = int(os.getenv("METRICS_REFRESH_SEC", "30"))
    MAINTENANCE_SEC: int = int(os.getenv("MAINTENANCE_SEC", "60"))

    # --- Rate limits (use-cases) ---
    RL_EVALUATE_PER_MIN: int = int(os.getenv("RL_EVALUATE_PER_MIN", "60"))
    RL_ORDERS_PER_MIN: int = int(os.getenv("RL_ORDERS_PER_MIN", "10"))
    RL_MARKET_CONTEXT_PER_HOUR: int = int(os.getenv("RL_MARKET_CONTEXT_PER_HOUR", "100"))

    # --- брокер (ccxt/paper/backtest) ---
    EXCHANGE: str = os.getenv("EXCHANGE", "binance")
    API_KEY: Optional[str] = os.getenv("API_KEY") or None
    API_SECRET: Optional[str] = os.getenv("API_SECRET") or None
    SUBACCOUNT: Optional[str] = os.getenv("SUBACCOUNT") or None

    # --- база данных ---
    DB_PATH: str = os.getenv("DB_PATH", "data/bot.sqlite")

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN") or None
    # Обратная совместимость: поддерживаем TELEGRAM_WEBHOOK_SECRET
    TELEGRAM_SECRET_TOKEN: Optional[str] = (
        os.getenv("TELEGRAM_SECRET_TOKEN") or os.getenv("TELEGRAM_WEBHOOK_SECRET") or None
    )

    # --- идемпотентность ---
    IDEMPOTENCY_TTL_SEC: int = int(os.getenv("IDEMPOTENCY_TTL_SEC", "300"))

    # --- time sync / drift ---
    TIME_DRIFT_LIMIT_MS: int = int(os.getenv("TIME_DRIFT_LIMIT_MS", os.getenv("MAX_TIME_DRIFT_MS", "1000")))
    TIME_DRIFT_URLS: List[str] = [
        u.strip() for u in (os.getenv("TIME_DRIFT_URLS") or "").split(",") if u.strip()
    ] or ["https://worldtimeapi.org/api/timezone/Etc/UTC"]

    # --- бэктест ---
    BACKTEST_CSV_PATH: str = os.getenv("BACKTEST_CSV_PATH", "data/backtest.csv")

    # --- базовые параметры риск/размер ---
    POSITION_SIZE: str = os.getenv("POSITION_SIZE", "0.00")  # строкой, далее переводим в Decimal
    STOP_LOSS_PCT: float | None = float(os.getenv("STOP_LOSS_PCT")) if os.getenv("STOP_LOSS_PCT") else None
    TAKE_PROFIT_PCT: float | None = float(os.getenv("TAKE_PROFIT_PCT")) if os.getenv("TAKE_PROFIT_PCT") else None
    TRAILING_PCT: float | None = float(os.getenv("TRAILING_PCT")) if os.getenv("TRAILING_PCT") else None

    # --- профиль решений (новое) ---
    DECISION_PROFILE: str = os.getenv("DECISION_PROFILE", "balanced").lower()

    # Ручные переопределения поверх профиля (если заданы):
    DECISION_RULE_WEIGHT: Optional[float] = float(os.getenv("DECISION_RULE_WEIGHT")) if os.getenv("DECISION_RULE_WEIGHT") else None
    DECISION_AI_WEIGHT: Optional[float] = float(os.getenv("DECISION_AI_WEIGHT")) if os.getenv("DECISION_AI_WEIGHT") else None
    DECISION_BUY_THRESHOLD: Optional[float] = float(os.getenv("DECISION_BUY_THRESHOLD")) if os.getenv("DECISION_BUY_THRESHOLD") else None
    DECISION_SELL_THRESHOLD: Optional[float] = float(os.getenv("DECISION_SELL_THRESHOLD")) if os.getenv("DECISION_SELL_THRESHOLD") else None

    # Исторические алиасы (на случай старого кода):
    SCORE_RULE_WEIGHT: Optional[float] = float(os.getenv("SCORE_RULE_WEIGHT")) if os.getenv("SCORE_RULE_WEIGHT") else None
    SCORE_AI_WEIGHT: Optional[float] = float(os.getenv("SCORE_AI_WEIGHT")) if os.getenv("SCORE_AI_WEIGHT") else None

    # --- профили по умолчанию ---
    _PROFILES: Dict[str, _DecisionProfile] = {
        "conservative": _DecisionProfile(
            name="conservative",
            rule_weight=0.75,
            ai_weight=0.25,
            buy_threshold=0.65,
            sell_threshold=0.35,
        ),
        "balanced": _DecisionProfile(
            name="balanced",
            rule_weight=0.50,
            ai_weight=0.50,
            buy_threshold=0.55,
            sell_threshold=0.45,
        ),
        "aggressive": _DecisionProfile(
            name="aggressive",
            rule_weight=0.35,
            ai_weight=0.65,
            buy_threshold=0.52,
            sell_threshold=0.48,
        ),
    }

    # --- helpers ---
    def _profile_base(self) -> _DecisionProfile:
        return self._PROFILES.get(self.DECISION_PROFILE, self._PROFILES["balanced"])

    def get_weights(self) -> Tuple[float, float]:
        base = self._profile_base()
        rule_w = self.DECISION_RULE_WEIGHT if self.DECISION_RULE_WEIGHT is not None else (self.SCORE_RULE_WEIGHT if self.SCORE_RULE_WEIGHT is not None else base.rule_weight)
        ai_w = self.DECISION_AI_WEIGHT if self.DECISION_AI_WEIGHT is not None else (self.SCORE_AI_WEIGHT if self.SCORE_AI_WEIGHT is not None else base.ai_weight)
        total = rule_w + ai_w
        if total <= 0:
            return (0.5, 0.5)
        return (rule_w / total, ai_w / total)

    def get_thresholds(self) -> Tuple[float, float]:
        base = self._profile_base()
        buy = self.DECISION_BUY_THRESHOLD if self.DECISION_BUY_THRESHOLD is not None else base.buy_threshold
        sell = self.DECISION_SELL_THRESHOLD if self.DECISION_SELL_THRESHOLD is not None else base.sell_threshold
        return (float(buy), float(sell))

    def get_profile_dict(self) -> Dict[str, Any]:
        rw, aw = self.get_weights()
        buy, sell = self.get_thresholds()
        return {"name": self._profile_base().name, "weights": {"rule": rw, "ai": aw}, "thresholds": {"buy": buy, "sell": sell}}

    @classmethod
    def build(cls) -> "Settings":
        s = cls()

        # Алиасы из README/Word для совместимости старых конфигов
        if os.getenv("RATE_LIMIT_EVALUATE_PER_MINUTE"):
            s.RL_EVALUATE_PER_MIN = int(os.getenv("RATE_LIMIT_EVALUATE_PER_MINUTE", "60"))
        if os.getenv("RATE_LIMIT_PLACE_ORDER_PER_MINUTE"):
            s.RL_ORDERS_PER_MIN = int(os.getenv("RATE_LIMIT_PLACE_ORDER_PER_MINUTE", "10"))
        if os.getenv("MAX_TIME_DRIFT_MS") and not os.getenv("TIME_DRIFT_LIMIT_MS"):
            s.TIME_DRIFT_LIMIT_MS = int(os.getenv("MAX_TIME_DRIFT_MS", "1000"))

        # Безопасный режим запрещает реальную торговлю
        if s.SAFE_MODE:
            s.ENABLE_TRADING = False

        # Гарантированный дефолт для источников времени
        if not s.TIME_DRIFT_URLS:
            s.TIME_DRIFT_URLS = ["https://worldtimeapi.org/api/timezone/Etc/UTC"]

        return s
