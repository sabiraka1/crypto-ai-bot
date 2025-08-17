# src/crypto_ai_bot/core/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Tuple, Optional


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


    # --- брокер (ccxt/paper/backtest) ---
    EXCHANGE: str = os.getenv("EXCHANGE", "binance")
    API_KEY: Optional[str] = os.getenv("API_KEY") or None
    API_SECRET: Optional[str] = os.getenv("API_SECRET") or None
    SUBACCOUNT: Optional[str] = os.getenv("SUBACCOUNT") or None

    # --- идемпотентность ---
    IDEMPOTENCY_TTL_SEC: int = int(os.getenv("IDEMPOTENCY_TTL_SEC", "300"))

    # --- time sync / drift ---
    TIME_DRIFT_LIMIT_MS: int = int(os.getenv("TIME_DRIFT_LIMIT_MS", "1000"))  # 1s
    TIME_DRIFT_URLS: list[str] = [
        u.strip() for u in os.getenv("TIME_DRIFT_URLS", "").split(",") if u.strip()
    ]

     or ["https://worldtimeapi.org/api/timezone/Etc/UTC"]# --- бэктест ---
    BACKTEST_CSV_PATH: str = os.getenv("BACKTEST_CSV_PATH", "data/backtest.csv")

    # --- базовые параметры риск/размер ---
    POSITION_SIZE: str = os.getenv("POSITION_SIZE", "0.00")  # строкой, далее переводим в Decimal
    STOP_LOSS_PCT: float | None = float(os.getenv("STOP_LOSS_PCT")) if os.getenv("STOP_LOSS_PCT") else None
    TAKE_PROFIT_PCT: float | None = float(os.getenv("TAKE_PROFIT_PCT")) if os.getenv("TAKE_PROFIT_PCT") else None
    TRAILING_PCT: float | None = float(os.getenv("TRAILING_PCT")) if os.getenv("TRAILING_PCT") else None

    # --- профиль решений (новое) ---
    # Если задать DECISION_PROFILE, то применяются веса/пороги из профиля.
    # Доступные дефолтные профили: conservative | balanced | aggressive
    DECISION_PROFILE: str = os.getenv("DECISION_PROFILE", "balanced").lower()

    # Ручные переопределения поверх профиля (если заданы):
    DECISION_RULE_WEIGHT: Optional[float] = (
        float(os.getenv("DECISION_RULE_WEIGHT")) if os.getenv("DECISION_RULE_WEIGHT") else None
    )
    DECISION_AI_WEIGHT: Optional[float] = (
        float(os.getenv("DECISION_AI_WEIGHT")) if os.getenv("DECISION_AI_WEIGHT") else None
    )
    DECISION_BUY_THRESHOLD: Optional[float] = (
        float(os.getenv("DECISION_BUY_THRESHOLD")) if os.getenv("DECISION_BUY_THRESHOLD") else None
    )
    DECISION_SELL_THRESHOLD: Optional[float] = (
        float(os.getenv("DECISION_SELL_THRESHOLD")) if os.getenv("DECISION_SELL_THRESHOLD") else None
    )

    # Исторические алиасы (на случай старого кода):
    SCORE_RULE_WEIGHT: Optional[float] = (
        float(os.getenv("SCORE_RULE_WEIGHT")) if os.getenv("SCORE_RULE_WEIGHT") else None
    )
    SCORE_AI_WEIGHT: Optional[float] = (
        float(os.getenv("SCORE_AI_WEIGHT")) if os.getenv("SCORE_AI_WEIGHT") else None
    )

    # --- профили по умолчанию ---
    _PROFILES: Dict[str, _DecisionProfile] = {
        "conservative": _DecisionProfile(
            name="conservative",
            rule_weight=0.75,  # больше доверяем правилам
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
            rule_weight=0.35,  # больше доверяем AI
            ai_weight=0.65,
            buy_threshold=0.52,
            sell_threshold=0.48,
        ),
    }

    # --- helpers ---

    def _profile_base(self) -> _DecisionProfile:
        return self._PROFILES.get(self.DECISION_PROFILE, self._PROFILES["balanced"])

    def get_weights(self) -> Tuple[float, float]:
        """
        Возвращает (rule_weight, ai_weight) с учётом переопределений ENV и старых алиасов.
        Сумма нормализуется в [0..1] если что-то пошло не так.
        """
        base = self._profile_base()
        rule_w = (
            self.DECISION_RULE_WEIGHT
            if self.DECISION_RULE_WEIGHT is not None
            else (self.SCORE_RULE_WEIGHT if self.SCORE_RULE_WEIGHT is not None else base.rule_weight)
        )
        ai_w = (
            self.DECISION_AI_WEIGHT
            if self.DECISION_AI_WEIGHT is not None
            else (self.SCORE_AI_WEIGHT if self.SCORE_AI_WEIGHT is not None else base.ai_weight)
        )
        total = rule_w + ai_w
        if total <= 0:
            return (0.5, 0.5)
        return (rule_w / total, ai_w / total)

    def get_thresholds(self) -> Tuple[float, float]:
        """
        Возвращает (buy_threshold, sell_threshold) с учётом ENV переопределений.
        """
        base = self._profile_base()
        buy = self.DECISION_BUY_THRESHOLD if self.DECISION_BUY_THRESHOLD is not None else base.buy_threshold
        sell = self.DECISION_SELL_THRESHOLD if self.DECISION_SELL_THRESHOLD is not None else base.sell_threshold
        return (float(buy), float(sell))

    def get_profile_dict(self) -> Dict[str, Any]:
        """
        Удобно отдавать в /config или в explain.
        """
        rw, aw = self.get_weights()
        buy, sell = self.get_thresholds()
        return {
            "name": self._profile_base().name,
            "weights": {"rule": rw, "ai": aw},
            "thresholds": {"buy": buy, "sell": sell},
        }

    # Фабрика: можно будет расширять (валидация, кросс-проверки)
    @classmethod
    def build(cls) -> "Settings":
        s = cls()
        # SAFE_MODE всегда выключает реальную торговлю
        if s.SAFE_MODE:
            s.ENABLE_TRADING = False
        return s
