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
    # --- базовые режимы ---
    MODE: str = os.getenv("MODE", "paper").lower()
    SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "1h")
    LIMIT_BARS: int = int(os.getenv("LIMIT_BARS", "300"))
    LOOKBACK_LIMIT: int = LIMIT_BARS

    ENABLE_TRADING: bool = os.getenv("ENABLE_TRADING", "false").lower() in {"1", "true", "yes"}
    SAFE_MODE: bool = os.getenv("SAFE_MODE", "true").lower() in {"1", "true", "yes"}

    # --- пути/БД ---
    DB_PATH: str = os.getenv("DB_PATH", "crypto.db")

    # --- оркестратор ---
    TICK_PERIOD_SEC: int = int(os.getenv("TICK_PERIOD_SEC", "60"))
    METRICS_REFRESH_SEC: int = int(os.getenv("METRICS_REFRESH_SEC", "30"))
    MAINTENANCE_SEC: int = int(os.getenv("MAINTENANCE_SEC", "60"))
    ORCHESTRATOR_AUTOSTART: bool = os.getenv("ORCHESTRATOR_AUTOSTART", "false").lower() in {"1", "true", "yes"}

    # --- Rate limits ---
    RL_EVALUATE_PER_MIN: int = int(os.getenv("RL_EVALUATE_PER_MIN", "60"))
    RL_ORDERS_PER_MIN: int = int(os.getenv("RL_ORDERS_PER_MIN", "10"))

    # --- брокер ---
    EXCHANGE: str = os.getenv("EXCHANGE", "binance")
    API_KEY: Optional[str] = os.getenv("API_KEY") or None
    API_SECRET: Optional[str] = os.getenv("API_SECRET") or None
    SUBACCOUNT: Optional[str] = os.getenv("SUBACCOUNT") or None

    # --- идемпотентность ---
    IDEMPOTENCY_TTL_SEC: int = int(os.getenv("IDEMPOTENCY_TTL_SEC", "300"))

    # --- time sync ---
    TIME_DRIFT_LIMIT_MS: int = int(os.getenv("TIME_DRIFT_LIMIT_MS", "1000"))
    TIME_DRIFT_URLS: List[str] = [
        u.strip() for u in os.getenv("TIME_DRIFT_URLS", "").split(",") if u.strip()
    ] or [
        "https://worldtimeapi.org/api/timezone/Etc/UTC",
        "https://timeapi.io/api/Time/current/zone?timeZone=UTC",
        "https://www.google.com",
        "https://www.cloudflare.com",
    ]

    # --- бэктест ---
    BACKTEST_CSV_PATH: str = os.getenv("BACKTEST_CSV_PATH", "data/backtest.csv")

    # --- риск/размер ---
    POSITION_SIZE: str = os.getenv("POSITION_SIZE", "0.00")
    STOP_LOSS_PCT: float | None = float(os.getenv("STOP_LOSS_PCT")) if os.getenv("STOP_LOSS_PCT") else None
    TAKE_PROFIT_PCT: float | None = float(os.getenv("TAKE_PROFIT_PCT")) if os.getenv("TAKE_PROFIT_PCT") else None
    TRAILING_PCT: float | None = float(os.getenv("TRAILING_PCT")) if os.getenv("TRAILING_PCT") else None

    # Рычаги риска
    MAX_POSITIONS: int = int(os.getenv("MAX_POSITIONS", "1"))
    MAX_SPREAD_BPS: int = int(os.getenv("MAX_SPREAD_BPS", "25"))
    RISK_HOURS_UTC: str = os.getenv("RISK_HOURS_UTC", "0-24")
    RISK_LOOKBACK_DAYS: int = int(os.getenv("RISK_LOOKBACK_DAYS", "7"))
    RISK_MAX_DRAWDOWN_PCT: float = float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "10"))
    RISK_SEQUENCE_WINDOW: int = int(os.getenv("RISK_SEQUENCE_WINDOW", "3"))
    RISK_MAX_LOSSES: int = int(os.getenv("RISK_MAX_LOSSES", "3"))

    # --- Telegram / webhooks ---
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = os.getenv("TELEGRAM_WEBHOOK_SECRET") or None
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN") or None
    ALERT_TELEGRAM_CHAT_ID: Optional[str] = os.getenv("ALERT_TELEGRAM_CHAT_ID") or None

    # --- профиль решений ---
    DECISION_PROFILE: str = os.getenv("DECISION_PROFILE", "balanced").lower()
    DECISION_RULE_WEIGHT: Optional[float] = float(os.getenv("DECISION_RULE_WEIGHT")) if os.getenv("DECISION_RULE_WEIGHT") else None
    DECISION_AI_WEIGHT: Optional[float] = float(os.getenv("DECISION_AI_WEIGHT")) if os.getenv("DECISION_AI_WEIGHT") else None
    DECISION_BUY_THRESHOLD: Optional[float] = float(os.getenv("DECISION_BUY_THRESHOLD")) if os.getenv("DECISION_BUY_THRESHOLD") else None
    DECISION_SELL_THRESHOLD: Optional[float] = float(os.getenv("DECISION_SELL_THRESHOLD")) if os.getenv("DECISION_SELL_THRESHOLD") else None

    # Исторические алиасы
    SCORE_RULE_WEIGHT: Optional[float] = float(os.getenv("SCORE_RULE_WEIGHT")) if os.getenv("SCORE_RULE_WEIGHT") else None
    SCORE_AI_WEIGHT: Optional[float] = float(os.getenv("SCORE_AI_WEIGHT")) if os.getenv("SCORE_AI_WEIGHT") else None

    # --- Event Bus ---
    BUS_DLQ_MAX: int = int(os.getenv("BUS_DLQ_MAX", "1000"))

    # --- Journal (events ring-buffer) ---
    JOURNAL_MAX_ROWS: int = int(os.getenv("JOURNAL_MAX_ROWS", "10000"))

    # --- Алерты ---
    ALERT_ON_DLQ: bool = os.getenv("ALERT_ON_DLQ", "true").lower() in {"1", "true", "yes"}
    ALERT_DLQ_EVERY_SEC: int = int(os.getenv("ALERT_DLQ_EVERY_SEC", "300"))
    ALERT_ON_LATENCY: bool = os.getenv("ALERT_ON_LATENCY", "false").lower() in {"1", "true", "yes"}
    DECISION_LATENCY_P99_ALERT_MS: int = int(os.getenv("DECISION_LATENCY_P99_ALERT_MS", "0"))
    ORDER_LATENCY_P99_ALERT_MS: int = int(os.getenv("ORDER_LATENCY_P99_ALERT_MS", "0"))
    FLOW_LATENCY_P99_ALERT_MS: int = int(os.getenv("FLOW_LATENCY_P99_ALERT_MS", "0"))

    # --- Performance budgets (p99), ms (дефолты по Word) ---
    PERF_BUDGET_DECISION_P99_MS: int = int(os.getenv("PERF_BUDGET_DECISION_P99_MS", "400"))
    PERF_BUDGET_ORDER_P99_MS: int = int(os.getenv("PERF_BUDGET_ORDER_P99_MS", "750"))
    PERF_BUDGET_FLOW_P99_MS: int = int(os.getenv("PERF_BUDGET_FLOW_P99_MS", "1500"))

    # --- Market Context источники ---
    CONTEXT_ENABLE: bool = os.getenv("CONTEXT_ENABLE", "true").lower() in {"1", "true", "yes"}
    CONTEXT_CACHE_TTL_SEC: int = int(os.getenv("CONTEXT_CACHE_TTL_SEC", "300"))
    CONTEXT_HTTP_TIMEOUT_SEC: float = float(os.getenv("CONTEXT_HTTP_TIMEOUT_SEC", "2.0"))
    CONTEXT_BTC_DOMINANCE_URL: str = os.getenv("CONTEXT_BTC_DOMINANCE_URL", "https://api.coingecko.com/api/v3/global")
    CONTEXT_FEAR_GREED_URL: str = os.getenv("CONTEXT_FEAR_GREED_URL", "https://api.alternative.me/fng/?limit=1")
    CONTEXT_DXY_URL: str = os.getenv("CONTEXT_DXY_URL", "")

    # --- Market Context веса (ручной режим) ---
    CONTEXT_DECISION_WEIGHT: float = float(os.getenv("CONTEXT_DECISION_WEIGHT", "0"))
    CTX_BTC_DOM_WEIGHT: float = float(os.getenv("CTX_BTC_DOM_WEIGHT", "0"))
    CTX_FNG_WEIGHT: float = float(os.getenv("CTX_FNG_WEIGHT", "0"))
    CTX_DXY_WEIGHT: float = float(os.getenv("CTX_DXY_WEIGHT", "0"))

    # --- Market Context пресет (простой режим) ---
    # off | simple | balanced | custom
    CONTEXT_PRESET: str = os.getenv("CONTEXT_PRESET", "off").lower()

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_JSON: bool = os.getenv("LOG_JSON", "false").lower() in {"1", "true", "yes"}

    # --- профили по умолчанию ---
    _PROFILES: Dict[str, _DecisionProfile] = {
        "conservative": _DecisionProfile("conservative", 0.75, 0.25, 0.65, 0.35),
        "balanced":     _DecisionProfile("balanced",     0.50, 0.50, 0.55, 0.45),
        "aggressive":   _DecisionProfile("aggressive",   0.35, 0.65, 0.52, 0.48),
    }

    def _profile_base(self) -> _DecisionProfile:
        return self._PROFILES.get(self.DECISION_PROFILE, self._PROFILES["balanced"])

    def get_weights(self) -> Tuple[float, float]:
        base = self._profile_base()
        rule_w = self.DECISION_RULE_WEIGHT if self.DECISION_RULE_WEIGHT is not None else (self.SCORE_RULE_WEIGHT if self.SCORE_RULE_WEIGHT is not None else base.rule_weight)
        ai_w = self.DECISION_AI_WEIGHT   if self.DECISION_AI_WEIGHT   is not None else (self.SCORE_AI_WEIGHT   if self.SCORE_AI_WEIGHT   is not None else base.ai_weight)
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

        # Safe-mode отключает торговлю
        if s.SAFE_MODE:
            s.ENABLE_TRADING = False

        # ---- ПРОСТОЙ ПРЕСЕТ КОНТЕКСТА ----
        # Срабатывает только если вручную веса не заданы (все нули).
        no_manual = (
            float(s.CONTEXT_DECISION_WEIGHT) == 0.0 and
            float(s.CTX_BTC_DOM_WEIGHT) == 0.0 and
            float(s.CTX_FNG_WEIGHT) == 0.0 and
            float(s.CTX_DXY_WEIGHT) == 0.0
        )

        if no_manual:
            if s.CONTEXT_PRESET == "off":
                s.CONTEXT_DECISION_WEIGHT = 0.0
            elif s.CONTEXT_PRESET == "simple":
                s.CONTEXT_DECISION_WEIGHT = 0.20
                s.CTX_FNG_WEIGHT = 1.0
                s.CTX_DXY_WEIGHT = 0.0
                s.CTX_BTC_DOM_WEIGHT = 0.0
            elif s.CONTEXT_PRESET == "balanced":
                s.CONTEXT_DECISION_WEIGHT = 0.20
                s.CTX_FNG_WEIGHT = 1.0
                s.CTX_DXY_WEIGHT = 1.0
                s.CTX_BTC_DOM_WEIGHT = 0.5
            # 'custom' или неизвестное — ничего не трогаем

        return s
