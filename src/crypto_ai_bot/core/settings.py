# src/crypto_ai_bot/core/settings.py
from __future__ import annotations

import os
import json
from dataclasses import dataclass, field, asdict
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional


# ───────────────────────── helpers: безопасный парсинг ENV ─────────────────────

def _getenv(key: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(key)
    if v is None or v == "":
        return default
    return v

def _as_bool(v: Optional[str], default: bool) -> bool:
    if v is None:
        return default
    s = v.strip().lower()
    return s in {"1", "true", "yes", "y", "on"}

def _as_int(v: Optional[str], default: int) -> int:
    if v is None:
        return default
    try:
        return int(v.strip())
    except Exception:
        return default

def _as_float(v: Optional[str], default: float) -> float:
    if v is None:
        return default
    try:
        return float(v.strip())
    except Exception:
        return default

def _as_decimal(v: Optional[str], default: Decimal) -> Decimal:
    if v is None:
        return default
    try:
        return v if isinstance(v, Decimal) else Decimal(str(v).strip())
    except (InvalidOperation, Exception):
        return default

def _as_json(v: Optional[str], default: Dict[str, Any]) -> Dict[str, Any]:
    if v is None:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


# ────────────────────────────── Settings dataclass ─────────────────────────────

@dataclass
class Settings:
    # ── режим/общие ────────────────────────────────────────────────────────────
    MODE: str = "paper"                    # "live" | "paper" | "backtest"
    EXCHANGE: str = "binance"              # имя обменника для адаптера
    SYMBOL: str = "BTC/USDT"               # нормализованный символ
    TIMEFRAME: str = "1h"                  # нормализованный TF
    FEATURE_LIMIT: int = 300               # сколько баров тянуть
    MIN_FEATURE_BARS: int = 100            # минимум баров для фич

    # ── решение/порог/веса ────────────────────────────────────────────────────
    DECISION_RULE_WEIGHT: Decimal = Decimal("0.7")
    DECISION_AI_WEIGHT: Decimal = Decimal("0.3")
    BUY_THRESHOLD: float = 0.60            # итоговый score ≥ → buy
    SELL_THRESHOLD: float = 0.40           # итоговый score ≤ → sell (если используете двусторонний порог)
    DEFAULT_ORDER_SIZE: Decimal = Decimal("0")  # если стратегия не проставила size

    # ── риск-правила (примерные дефолты; стратегия может не пользоваться всеми) ─
    MAX_DRAWDOWN_PCT: Decimal = Decimal("20")   # дневной DD, %
    MAX_SEQ_LOSSES: int = 5                     # макс. подряд убытков
    MAX_EXPOSURE_QUOTE: Decimal = Decimal("5000")  # ограничение экспозиции в котируемой валюте

    # ── health ────────────────────────────────────────────────────────────────
    HEALTHCHECK_SYMBOL: Optional[str] = None
    HEALTHCHECK_TIMEOUT_SEC: float = 2.0

    # ── БД / SQLite ───────────────────────────────────────────────────────────
    DB_PATH: str = "data/bot.sqlite3"
    SQLITE_WAL: bool = True
    SQLITE_BUSY_TIMEOUT_MS: int = 5000

    # ── идемпотентность ───────────────────────────────────────────────────────
    IDEMPOTENCY_TTL_SEC: int = 900

    # ── Telegram (опционально) ────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = None

    # ── HTTP/клиент/ретраи (используется в utils.http_client и брокерах) ─────
    HTTP_TIMEOUT_SEC: float = 10.0
    HTTP_RETRIES: int = 2
    HTTP_BACKOFF_BASE_SEC: float = 0.2    # эксп.бэкофф базовый
    HTTP_BACKOFF_JITTER_SEC: float = 0.1  # случайная добавка
    HTTP_RATE_LIMIT_PER_SEC: Optional[float] = None  # если нужен простой RL

    # ── live broker (CCXT) ────────────────────────────────────────────────────
    CCXT_API_KEY: Optional[str] = None
    CCXT_API_SECRET: Optional[str] = None
    CCXT_PASSWORD: Optional[str] = None
    CCXT_UID: Optional[str] = None

    # ── paper broker ──────────────────────────────────────────────────────────
    PAPER_FEE_PCT: Decimal = Decimal("0.001")       # 0.1%
    PAPER_SLIPPAGE_PCT: Decimal = Decimal("0.0005") # 0.05%
    PAPER_LATENCY_MS: int = 50

    # ── backtest broker ───────────────────────────────────────────────────────
    BACKTEST_CSV: Optional[str] = None
    BACKTEST_INITIAL_BALANCE: Decimal = Decimal("10000")
    BACKTEST_FEE_PCT: Decimal = Decimal("0.0005")
    BACKTEST_SLIPPAGE_PCT: Decimal = Decimal("0.0002")

    # ── оркестратор/планировщик ───────────────────────────────────────────────
    SCHEDULE_EVAL_SECONDS: int = 60
    SCHEDULE_MAINTENANCE_SECONDS: int = 600  # обслуживание: VACUUM/optimize/purge

    # ── прочее/служебное ──────────────────────────────────────────────────────
    SAFE_MODE: bool = False                 # если True → торговля выключена независимо от ENABLE_TRADING
    ENABLE_TRADING: bool = True             # общий флаг «можно ли исполнять ордера»
    EXTRA: Dict[str, Any] = field(default_factory=dict)

    # ──────────────────────── конструкторы/валидаторы ─────────────────────────

    @classmethod
    def build(cls) -> "Settings":
        """
        Единая точка загрузки конфигурации из ENV.
        ВАЖНО: никакого чтения ENV за пределами этого метода в проекте.
        """
        s = cls()

        # режим/общие
        s.MODE = (_getenv("MODE", s.MODE) or s.MODE).lower()
        s.EXCHANGE = _getenv("EXCHANGE", s.EXCHANGE) or s.EXCHANGE
        s.SYMBOL = _getenv("SYMBOL", s.SYMBOL) or s.SYMBOL
        s.TIMEFRAME = _getenv("TIMEFRAME", s.TIMEFRAME) or s.TIMEFRAME
        s.FEATURE_LIMIT = _as_int(_getenv("FEATURE_LIMIT"), s.FEATURE_LIMIT)
        s.MIN_FEATURE_BARS = _as_int(_getenv("MIN_FEATURE_BARS"), s.MIN_FEATURE_BARS)

        # веса/пороги
        s.DECISION_RULE_WEIGHT = _as_decimal(_getenv("DECISION_RULE_WEIGHT"), s.DECISION_RULE_WEIGHT)
        s.DECISION_AI_WEIGHT = _as_decimal(_getenv("DECISION_AI_WEIGHT"), s.DECISION_AI_WEIGHT)
        s.BUY_THRESHOLD = _as_float(_getenv("BUY_THRESHOLD"), s.BUY_THRESHOLD)
        s.SELL_THRESHOLD = _as_float(_getenv("SELL_THRESHOLD"), s.SELL_THRESHOLD)
        s.DEFAULT_ORDER_SIZE = _as_decimal(_getenv("DEFAULT_ORDER_SIZE"), s.DEFAULT_ORDER_SIZE)

        # риск
        s.MAX_DRAWDOWN_PCT = _as_decimal(_getenv("MAX_DRAWDOWN_PCT"), s.MAX_DRAWDOWN_PCT)
        s.MAX_SEQ_LOSSES = _as_int(_getenv("MAX_SEQ_LOSSES"), s.MAX_SEQ_LOSSES)
        s.MAX_EXPOSURE_QUOTE = _as_decimal(_getenv("MAX_EXPOSURE_QUOTE"), s.MAX_EXPOSURE_QUOTE)

        # health
        s.HEALTHCHECK_SYMBOL = _getenv("HEALTHCHECK_SYMBOL", s.HEALTHCHECK_SYMBOL)
        s.HEALTHCHECK_TIMEOUT_SEC = _as_float(_getenv("HEALTHCHECK_TIMEOUT_SEC"), s.HEALTHCHECK_TIMEOUT_SEC)

        # БД
        s.DB_PATH = _getenv("DB_PATH", s.DB_PATH) or s.DB_PATH
        s.SQLITE_WAL = _as_bool(_getenv("SQLITE_WAL"), s.SQLITE_WAL)
        s.SQLITE_BUSY_TIMEOUT_MS = _as_int(_getenv("SQLITE_BUSY_TIMEOUT_MS"), s.SQLITE_BUSY_TIMEOUT_MS)

        # идемпотентность
        s.IDEMPOTENCY_TTL_SEC = _as_int(_getenv("IDEMPOTENCY_TTL_SEC"), s.IDEMPOTENCY_TTL_SEC)

        # Telegram
        s.TELEGRAM_BOT_TOKEN = _getenv("TELEGRAM_BOT_TOKEN", s.TELEGRAM_BOT_TOKEN)
        s.TELEGRAM_WEBHOOK_SECRET = _getenv("TELEGRAM_WEBHOOK_SECRET", s.TELEGRAM_WEBHOOK_SECRET)

        # HTTP
        s.HTTP_TIMEOUT_SEC = _as_float(_getenv("HTTP_TIMEOUT_SEC"), s.HTTP_TIMEOUT_SEC)
        s.HTTP_RETRIES = _as_int(_getenv("HTTP_RETRIES"), s.HTTP_RETRIES)
        s.HTTP_BACKOFF_BASE_SEC = _as_float(_getenv("HTTP_BACKOFF_BASE_SEC"), s.HTTP_BACKOFF_BASE_SEC)
        s.HTTP_BACKOFF_JITTER_SEC = _as_float(_getenv("HTTP_BACKOFF_JITTER_SEC"), s.HTTP_BACKOFF_JITTER_SEC)
        rl = _getenv("HTTP_RATE_LIMIT_PER_SEC")
        s.HTTP_RATE_LIMIT_PER_SEC = None if rl in (None, "", "0", "none", "null") else _as_float(rl, 0.0)

        # CCXT
        s.CCXT_API_KEY = _getenv("CCXT_API_KEY", s.CCXT_API_KEY)
        s.CCXT_API_SECRET = _getenv("CCXT_API_SECRET", s.CCXT_API_SECRET)
        s.CCXT_PASSWORD = _getenv("CCXT_PASSWORD", s.CCXT_PASSWORD)
        s.CCXT_UID = _getenv("CCXT_UID", s.CCXT_UID)

        # paper
        s.PAPER_FEE_PCT = _as_decimal(_getenv("PAPER_FEE_PCT"), s.PAPER_FEE_PCT)
        s.PAPER_SLIPPAGE_PCT = _as_decimal(_getenv("PAPER_SLIPPAGE_PCT"), s.PAPER_SLIPPAGE_PCT)
        s.PAPER_LATENCY_MS = _as_int(_getenv("PAPER_LATENCY_MS"), s.PAPER_LATENCY_MS)

        # backtest
        s.BACKTEST_CSV = _getenv("BACKTEST_CSV", s.BACKTEST_CSV)
        s.BACKTEST_INITIAL_BALANCE = _as_decimal(_getenv("BACKTEST_INITIAL_BALANCE"), s.BACKTEST_INITIAL_BALANCE)
        s.BACKTEST_FEE_PCT = _as_decimal(_getenv("BACKTEST_FEE_PCT"), s.BACKTEST_FEE_PCT)
        s.BACKTEST_SLIPPAGE_PCT = _as_decimal(_getenv("BACKTEST_SLIPPAGE_PCT"), s.BACKTEST_SLIPPAGE_PCT)

        # оркестратор
        s.SCHEDULE_EVAL_SECONDS = _as_int(_getenv("SCHEDULE_EVAL_SECONDS"), s.SCHEDULE_EVAL_SECONDS)
        s.SCHEDULE_MAINTENANCE_SECONDS = _as_int(_getenv("SCHEDULE_MAINTENANCE_SECONDS"), s.SCHEDULE_MAINTENANCE_SECONDS)

        # флаги безопасности
        s.SAFE_MODE = _as_bool(_getenv("SAFE_MODE"), s.SAFE_MODE)
        s.ENABLE_TRADING = _as_bool(_getenv("ENABLE_TRADING"), s.ENABLE_TRADING)

        # прочее (JSON в EXTRA)
        s.EXTRA = _as_json(_getenv("EXTRA_JSON"), s.EXTRA)

        # финальная валидация/нормализация
        s._validate_and_fix()

        return s

    # ───────────────────────────── util-методы ────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Удобный дамп для логов/диагностики (секреты не фильтруем здесь намеренно)."""
        d = asdict(self)
        return d

    # ──────────────────────── приватная валидация ─────────────────────────────

    def _validate_and_fix(self) -> None:
        errors: list[str] = []

        # MODE
        if self.MODE not in {"live", "paper", "backtest"}:
            errors.append(f"MODE must be one of ['live','paper','backtest'], got {self.MODE!r}")

        # веса → [0..1], нормализация суммы
        self.DECISION_RULE_WEIGHT = _clamp_dec01(self.DECISION_RULE_WEIGHT)
        self.DECISION_AI_WEIGHT = _clamp_dec01(self.DECISION_AI_WEIGHT)
        wsum = (self.DECISION_RULE_WEIGHT + self.DECISION_AI_WEIGHT)
        if wsum == 0:
            # если оба 0 — вернём дефолты
            self.DECISION_RULE_WEIGHT = Decimal("0.7")
            self.DECISION_AI_WEIGHT = Decimal("0.3")
            wsum = Decimal("1.0")
        # нормализуем к сумме 1
        self.DECISION_RULE_WEIGHT = (self.DECISION_RULE_WEIGHT / wsum).quantize(Decimal("0.0001"))
        self.DECISION_AI_WEIGHT = (self.DECISION_AI_WEIGHT / wsum).quantize(Decimal("0.0001"))

        # пороги
        self.BUY_THRESHOLD = min(max(self.BUY_THRESHOLD, 0.0), 1.0)
        self.SELL_THRESHOLD = min(max(self.SELL_THRESHOLD, 0.0), 1.0)

        # безопасность: SAFE_MODE → торговля выключена
        if self.SAFE_MODE:
            self.ENABLE_TRADING = False

        # числа/границы
        if self.FEATURE_LIMIT < 10:
            errors.append("FEATURE_LIMIT must be >= 10")
        if self.MIN_FEATURE_BARS < 10:
            errors.append("MIN_FEATURE_BARS must be >= 10")
        if self.SCHEDULE_EVAL_SECONDS < 5:
            errors.append("SCHEDULE_EVAL_SECONDS must be >= 5")
        if self.SCHEDULE_MAINTENANCE_SECONDS < 30:
            errors.append("SCHEDULE_MAINTENANCE_SECONDS must be >= 30")
        if self.IDEMPOTENCY_TTL_SEC < 60:
            errors.append("IDEMPOTENCY_TTL_SEC must be >= 60")

        # комиссии/слippage не отрицательные
        for name in (
            "PAPER_FEE_PCT", "PAPER_SLIPPAGE_PCT",
            "BACKTEST_FEE_PCT", "BACKTEST_SLIPPAGE_PCT",
        ):
            if getattr(self, name) < 0:
                errors.append(f"{name} must be >= 0")

        # таймауты
        if self.HTTP_TIMEOUT_SEC <= 0:
            errors.append("HTTP_TIMEOUT_SEC must be > 0")
        if self.HTTP_RETRIES < 0:
            errors.append("HTTP_RETRIES must be >= 0")

        # БД
        if not self.DB_PATH or not isinstance(self.DB_PATH, str):
            errors.append("DB_PATH must be non-empty string")

        # итог
        if errors:
            # объединяем в одно исключение с читабельным текстом
            raise ValueError("Settings validation errors:\n - " + "\n - ".join(errors))


def _clamp_dec01(x: Decimal) -> Decimal:
    try:
        if x < 0:
            return Decimal("0")
        if x > 1:
            return Decimal("1")
        return x
    except Exception:
        return Decimal("0")
