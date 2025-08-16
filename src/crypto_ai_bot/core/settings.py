from __future__ import annotations

"""
core/settings.py — ЕДИНСТВЕННОЕ место чтения ENV.
Возвращает валидированный и нормализованный Settings через Settings.build().

Жёсткие гарантии:
- Только os.getenv (или .env через python-dotenv) — никаких других побочных эффектов.
- Деньги: Decimal, время: значения в мс, секундных интервалах — int.
- Веса и пороги — валидируются и при необходимости нормализуются.
- Все значения доступны как атрибуты экземпляра Settings.
"""

import os
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from typing import Optional

try:
    # Разрешено: загрузка .env только здесь
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(override=False)
except Exception:
    # Библиотека может отсутствовать — это не критично
    pass


def _to_bool(v: Optional[str], default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _to_int(v: Optional[str], default: int) -> int:
    try:
        return int(str(v)) if v is not None else default
    except Exception:
        return default


def _to_decimal(v: Optional[str], default: Decimal) -> Decimal:
    if v is None or v == "":
        return default
    try:
        # строго через строку
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return default


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


@dataclass
class Settings:
    # --- Режим работы / брокер ---
    MODE: str                     # "live" | "paper" | "backtest"
    EXCHANGE_ID: str              # например "binance" (для live/backtest)
    BROKER: str                   # "ccxt" | "paper" | "backtest"

    # --- Торговля / символы ---
    SYMBOL: str                   # "BTC/USDT"
    TIMEFRAME: str                # "1h"
    DEFAULT_LIMIT: int            # кол-во свечей по умолчанию
    DEFAULT_ORDER_SIZE: str       # строка, чтобы не потерять точность при Decimal

    # --- Пороги решений / веса ---
    THRESHOLD_BUY: float
    THRESHOLD_SELL: float
    SCORE_RULE_WEIGHT: float
    SCORE_AI_WEIGHT: float

    # --- Идемпотентность ---
    IDEMPOTENCY_TTL_S: int

    # --- Time sync ---
    TIME_DRIFT_LIMIT_MS: int

    # --- Rate limit ---
    RL_EVALUATE_CALLS: int
    RL_EVALUATE_PERIOD_S: int
    RL_EXECUTE_CALLS: int
    RL_EXECUTE_PERIOD_S: int

    # --- HTTP / Circuit Breaker (используются в utils/http_client и брокерах) ---
    HTTP_TIMEOUT_S: float
    HTTP_RETRIES: int
    HTTP_BACKOFF_BASE: float
    HTTP_BACKOFF_JITTER: float

    CB_FAIL_THRESHOLD: int
    CB_OPEN_SECONDS: float
    CB_TIMEOUT_S: float

    # --- Paper/Backtest параметры ---
    PAPER_COMMISSION_PCT: Decimal
    PAPER_SLIPPAGE_PCT: Decimal

    # --- Storage / БД ---
    DB_PATH: str

    # --- Безопасность ---
    SAFE_MODE: bool               # если True — торговля принудительно запрещена, даже если ENABLE_TRADING=True
    ENABLE_TRADING: bool          # общий флаг торговли (для live/paper)

    @classmethod
    def build(cls) -> "Settings":
        # --- Режимы/брокер ---
        MODE = os.getenv("MODE", "paper").strip().lower()
        if MODE not in {"live", "paper", "backtest"}:
            MODE = "paper"

        # Явное имя брокера (приземляем режим на реализацию)
        if MODE == "live":
            BROKER = os.getenv("BROKER", "ccxt").strip().lower()
        elif MODE == "paper":
            BROKER = "paper"
        else:
            BROKER = "backtest"

        EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binance").strip().lower()

        # --- Торговля ---
        SYMBOL = os.getenv("SYMBOL", "BTC/USDT").strip()
        TIMEFRAME = os.getenv("TIMEFRAME", "1h").strip()
        DEFAULT_LIMIT = _to_int(os.getenv("DEFAULT_LIMIT"), 300)
        DEFAULT_ORDER_SIZE = os.getenv("DEFAULT_ORDER_SIZE", "0.01").strip()

        # --- Пороги/веса ---
        THRESHOLD_BUY = float(os.getenv("THRESHOLD_BUY", "0.55"))
        THRESHOLD_SELL = float(os.getenv("THRESHOLD_SELL", "0.45"))
        # Гарантия осмысленных порогов
        if not (0.0 <= THRESHOLD_SELL <= 1.0):
            THRESHOLD_SELL = 0.45
        if not (0.0 <= THRESHOLD_BUY <= 1.0):
            THRESHOLD_BUY = 0.55
        if THRESHOLD_BUY <= THRESHOLD_SELL:
            # минимальный зазор 0.05
            mid = 0.50
            THRESHOLD_SELL = min(0.49, mid - 0.05)
            THRESHOLD_BUY = max(0.51, mid + 0.05)

        SCORE_RULE_WEIGHT = _clamp01(float(os.getenv("SCORE_RULE_WEIGHT", "0.5")))
        SCORE_AI_WEIGHT = _clamp01(float(os.getenv("SCORE_AI_WEIGHT", "0.5")))
        # Нормализация весов, если сумма > 1
        s = SCORE_RULE_WEIGHT + SCORE_AI_WEIGHT
        if s == 0.0:
            SCORE_RULE_WEIGHT, SCORE_AI_WEIGHT = 0.5, 0.5
        elif s > 1.0:
            SCORE_RULE_WEIGHT = SCORE_RULE_WEIGHT / s
            SCORE_AI_WEIGHT = SCORE_AI_WEIGHT / s

        # --- Идемпотентность / time sync ---
        IDEMPOTENCY_TTL_S = _to_int(os.getenv("IDEMPOTENCY_TTL_S"), 300)
        TIME_DRIFT_LIMIT_MS = _to_int(os.getenv("TIME_DRIFT_LIMIT_MS"), 1000)

        # --- Rate Limit ---
        RL_EVALUATE_CALLS = _to_int(os.getenv("RL_EVALUATE_CALLS"), 60)
        RL_EVALUATE_PERIOD_S = _to_int(os.getenv("RL_EVALUATE_PERIOD_S"), 60)
        RL_EXECUTE_CALLS = _to_int(os.getenv("RL_EXECUTE_CALLS"), 10)
        RL_EXECUTE_PERIOD_S = _to_int(os.getenv("RL_EXECUTE_PERIOD_S"), 60)

        # --- HTTP / CB ---
        HTTP_TIMEOUT_S = float(os.getenv("HTTP_TIMEOUT_S", "5.0"))
        HTTP_RETRIES = _to_int(os.getenv("HTTP_RETRIES"), 2)
        HTTP_BACKOFF_BASE = float(os.getenv("HTTP_BACKOFF_BASE", "0.3"))
        HTTP_BACKOFF_JITTER = float(os.getenv("HTTP_BACKOFF_JITTER", "0.2"))

        CB_FAIL_THRESHOLD = _to_int(os.getenv("CB_FAIL_THRESHOLD"), 3)
        CB_OPEN_SECONDS = float(os.getenv("CB_OPEN_SECONDS", "5.0"))
        CB_TIMEOUT_S = float(os.getenv("CB_TIMEOUT_S", "2.5"))

        # --- Paper/Backtest параметры ---
        PAPER_COMMISSION_PCT = _to_decimal(os.getenv("PAPER_COMMISSION_PCT"), Decimal("0.001"))  # 0.1%
        PAPER_SLIPPAGE_PCT = _to_decimal(os.getenv("PAPER_SLIPPAGE_PCT"), Decimal("0.0005"))     # 0.05%

        # --- Storage ---
        DB_PATH = os.getenv("DB_PATH", "data/bot.sqlite").strip()

        # --- Безопасность ---
        SAFE_MODE = _to_bool(os.getenv("SAFE_MODE"), False)
        ENABLE_TRADING = _to_bool(os.getenv("ENABLE_TRADING"), MODE != "backtest")
        if SAFE_MODE:
            ENABLE_TRADING = False

        return cls(
            MODE=MODE,
            EXCHANGE_ID=EXCHANGE_ID,
            BROKER=BROKER,
            SYMBOL=SYMBOL,
            TIMEFRAME=TIMEFRAME,
            DEFAULT_LIMIT=DEFAULT_LIMIT,
            DEFAULT_ORDER_SIZE=DEFAULT_ORDER_SIZE,
            THRESHOLD_BUY=THRESHOLD_BUY,
            THRESHOLD_SELL=THRESHOLD_SELL,
            SCORE_RULE_WEIGHT=SCORE_RULE_WEIGHT,
            SCORE_AI_WEIGHT=SCORE_AI_WEIGHT,
            IDEMPOTENCY_TTL_S=IDEMPOTENCY_TTL_S,
            TIME_DRIFT_LIMIT_MS=TIME_DRIFT_LIMIT_MS,
            RL_EVALUATE_CALLS=RL_EVALUATE_CALLS,
            RL_EVALUATE_PERIOD_S=RL_EVALUATE_PERIOD_S,
            RL_EXECUTE_CALLS=RL_EXECUTE_CALLS,
            RL_EXECUTE_PERIOD_S=RL_EXECUTE_PERIOD_S,
            HTTP_TIMEOUT_S=HTTP_TIMEOUT_S,
            HTTP_RETRIES=HTTP_RETRIES,
            HTTP_BACKOFF_BASE=HTTP_BACKOFF_BASE,
            HTTP_BACKOFF_JITTER=HTTP_BACKOFF_JITTER,
            CB_FAIL_THRESHOLD=CB_FAIL_THRESHOLD,
            CB_OPEN_SECONDS=CB_OPEN_SECONDS,
            CB_TIMEOUT_S=CB_TIMEOUT_S,
            PAPER_COMMISSION_PCT=PAPER_COMMISSION_PCT,
            PAPER_SLIPPAGE_PCT=PAPER_SLIPPAGE_PCT,
            DB_PATH=DB_PATH,
            SAFE_MODE=SAFE_MODE,
            ENABLE_TRADING=ENABLE_TRADING,
        )
