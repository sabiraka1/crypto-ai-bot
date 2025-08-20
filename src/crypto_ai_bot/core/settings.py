# src/crypto_ai_bot/core/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _get_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _get_int(name: str, default: int) -> int:
    v = os.getenv(name)
    try:
        return int(v) if v is not None else default
    except Exception:
        return default


def _get_float(name: str, default: float) -> float:
    v = os.getenv(name)
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


@dataclass
class Settings:
    # --- режим/общие ---
    MODE: str = "paper"                     # "paper" | "live"
    ENABLE_TRADING: bool = False            # доп. kill-switch
    SYMBOL: str = "BTC/USDT"
    DB_PATH: str = "/data/bot.sqlite"

    # --- брокер/Gate.io/CCXT ---
    EXCHANGE: str = os.getenv("EXCHANGE", "gateio")
    API_KEY: Optional[str] = None
    API_SECRET: Optional[str] = None

    # --- риск/исполнение ---
    FEE_BPS: int = 20                       # 0.20%
    SLIPPAGE_BPS: int = 20                  # 0.20%
    MAX_SPREAD_BPS: int = 50                # 0.50%
    IDEMPOTENCY_BUCKET_MS: int = 15_000     # окно идемпотентности

    # --- интервалы оркестратора ---
    EVAL_INTERVAL_SEC: int = 60
    EXITS_INTERVAL_SEC: int = 5
    RECONCILE_INTERVAL_SEC: int = 60
    WATCHDOG_INTERVAL_SEC: int = 15

    # --- event bus ---
    EVENTBUS_MAX_QUEUE: int = 1024
    EVENTBUS_CONCURRENCY: int = 4

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_BOT_SECRET: Optional[str] = None

    # --- Circuit Breaker (для брокера) ---
    CB_FAIL_THRESHOLD: int = 5
    CB_OPEN_TIMEOUT_SEC: float = 30.0
    CB_HALF_OPEN_CALLS: int = 1
    CB_WINDOW_SEC: float = 60.0

    @classmethod
    def load(cls) -> "Settings":
        s = cls(
            MODE=os.getenv("MODE", "paper").strip().lower(),
            ENABLE_TRADING=_get_bool("ENABLE_TRADING", False),
            SYMBOL=os.getenv("SYMBOL", "BTC/USDT"),
            DB_PATH=os.getenv("DB_PATH", "/data/bot.sqlite"),
            EXCHANGE=os.getenv("EXCHANGE", "gateio"),
            API_KEY=os.getenv("API_KEY") or os.getenv("GATE_API_KEY"),
            API_SECRET=os.getenv("API_SECRET") or os.getenv("GATE_API_SECRET"),
            FEE_BPS=_get_int("FEE_BPS", 20),
            SLIPPAGE_BPS=_get_int("SLIPPAGE_BPS", 20),
            MAX_SPREAD_BPS=_get_int("MAX_SPREAD_BPS", 50),
            IDEMPOTENCY_BUCKET_MS=_get_int("IDEMPOTENCY_BUCKET_MS", 15_000),
            EVAL_INTERVAL_SEC=_get_int("EVAL_INTERVAL_SEC", 60),
            EXITS_INTERVAL_SEC=_get_int("EXITS_INTERVAL_SEC", 5),
            RECONCILE_INTERVAL_SEC=_get_int("RECONCILE_INTERVAL_SEC", 60),
            WATCHDOG_INTERVAL_SEC=_get_int("WATCHDOG_INTERVAL_SEC", 15),
            EVENTBUS_MAX_QUEUE=_get_int("EVENTBUS_MAX_QUEUE", 1024),
            EVENTBUS_CONCURRENCY=_get_int("EVENTBUS_CONCURRENCY", 4),
            TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN"),
            TELEGRAM_BOT_SECRET=os.getenv("TELEGRAM_BOT_SECRET"),
            CB_FAIL_THRESHOLD=_get_int("CB_FAIL_THRESHOLD", 5),
            CB_OPEN_TIMEOUT_SEC=_get_float("CB_OPEN_TIMEOUT_SEC", 30.0),
            CB_HALF_OPEN_CALLS=_get_int("CB_HALF_OPEN_CALLS", 1),
            CB_WINDOW_SEC=_get_float("CB_WINDOW_SEC", 60.0),
        )
        s._validate()
        return s

    # --- валидация прод-режима и обязательных параметров ---
    def _validate(self) -> None:
        if not self.DB_PATH:
            raise ValueError("DB_PATH must be set")

        mode = (self.MODE or "paper").lower()
        if mode not in ("paper", "live"):
            raise ValueError(f"Unsupported MODE={self.MODE}. Use 'paper' or 'live'.")

        # В live-режиме и при включённой торговле ключи обязательны
        if mode == "live" and self.ENABLE_TRADING:
            if not self.API_KEY or not self.API_SECRET:
                raise ValueError("API_KEY and API_SECRET are required for MODE=live with ENABLE_TRADING=true")

        # Формальные проверки торговых параметров
        if self.FEE_BPS < 0 or self.SLIPPAGE_BPS < 0 or self.MAX_SPREAD_BPS < 0:
            raise ValueError("FEE_BPS/SLIPPAGE_BPS/MAX_SPREAD_BPS must be non-negative")

        if self.IDEMPOTENCY_BUCKET_MS <= 0:
            raise ValueError("IDEMPOTENCY_BUCKET_MS must be positive")
