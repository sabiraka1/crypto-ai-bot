# -*- coding: utf-8 -*-
"""
Unified Settings (Phase 2)
Single source of truth for all configuration.
Usage:
    from crypto_ai_bot.core.settings import Settings
    cfg = Settings.build()
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(x: str | int | None, default: bool = False) -> bool:
    if x is None:
        return default
    if isinstance(x, int):
        return bool(x)
    s = str(x).strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


def _as_int(x: str | int | None, default: int) -> int:
    try:
        return int(x) if x is not None else default
    except Exception:
        return default


def _as_float(x: str | float | None, default: float) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


@dataclass
class Settings:
    # --- runtime / env ---
    TZ: str = "UTC"
    LOG_LEVEL: str = "INFO"

    # --- exchange/basic ---
    EXCHANGE_NAME: str = "gateio"
    SYMBOL: str = "BTC/USDT"
    TIMEFRAME: str = "15m"
    OHLCV_LIMIT: int = 200
    AGGREGATOR_LIMIT: int = 200
    ATR_PERIOD: int = 14

    # --- credentials (optional) ---
    API_KEY: str = ""
    API_SECRET: str = ""
    GATE_API_KEY: str = ""
    GATE_API_SECRET: str = ""

    # --- trading modes ---
    ENABLE_TRADING: bool = False
    SAFE_MODE: bool = True
    PAPER_MODE: bool = True

    # --- trading sizing / risk ---
    TRADE_AMOUNT: float = 10.0
    MAX_CONCURRENT_POS: int = 1
    STOP_LOSS_PCT: float = 2.0
    TAKE_PROFIT_PCT: float = 1.5
    TRAILING_STOP_ENABLE: bool = True
    TRAILING_STOP_PCT: float = 0.5
    POST_SALE_COOLDOWN: int = 60

    # --- multi-TP optional ---
    TP1_PCT: float = 0.5
    TP1_SIZE: float = 0.25
    TP2_PCT: float = 1.0
    TP2_SIZE: float = 0.25
    TP3_PCT: float = 1.5
    TP3_SIZE: float = 0.25
    TP4_PCT: float = 2.0
    TP4_SIZE: float = 0.25

    # --- portfolio/risk guard ---
    MAX_CONSECUTIVE_LOSSES: int = 5
    MIN_WIN_RATE: int = 35
    NEGATIVE_SHARPE_LIMIT: int = 0
    POOR_RR_THRESHOLD: float = 0.5
    DAILY_MAX_DRAWDOWN: float = 0.06
    MAX_DRAWDOWN_PCT: float = 15.0

    # --- market gates ---
    MAX_SPREAD_BPS: int = 15
    MIN_24H_VOLUME_USD: float = 1_000_000.0
    TRADING_HOUR_START: int = 0
    TRADING_HOUR_END: int = 24

    # --- AI/score ---
    AI_ENABLE: bool = True
    AI_FAILOVER_SCORE: float = 0.55
    AI_MIN_TO_TRADE: float = 0.55
    ENFORCE_AI_GATE: bool = True
    MIN_SCORE_TO_BUY: float = 0.65
    POSITION_MIN_FRACTION: float = 0.30
    POSITION_MAX_FRACTION: float = 1.00

    # --- context (penalties/bonuses) ---
    USE_CONTEXT_PENALTIES: bool = False
    CTX_BTC_DOM_ALTS_ONLY: bool = True
    CTX_BTC_DOM_THRESH: int = 52
    CTX_BTC_DOM_PENALTY: float = -0.05
    CTX_DXY_DELTA_THRESH: float = 0.5
    CTX_DXY_PENALTY: float = -0.05
    CTX_FNG_OVERHEATED: int = 75
    CTX_FNG_UNDERSHOOT: int = 25
    CTX_FNG_PENALTY: float = -0.05
    CTX_FNG_BONUS: float = 0.03
    CTX_SCORE_CLAMP_MIN: float = 0.0
    CTX_SCORE_CLAMP_MAX: float = 1.0

    # --- files / dirs (paper/live) ---
    DATA_DIR: str = "data"
    LOGS_DIR: str = "logs"
    MODEL_DIR: str = "models"
    CLOSED_TRADES_CSV: str = "closed_trades.csv"
    SIGNALS_CSV: str = "signals_snapshots.csv"
    PAPER_START_BALANCE_USD: float = 1000.0
    PAPER_FEE_BPS: int = 8
    PAPER_SLIPPAGE_BPS: int = 10
    PAPER_BALANCE_FILE: str = "paper_balance.json"
    PAPER_POSITIONS_FILE: str = "paper_positions.json"
    PAPER_ORDERS_FILE: str = "paper_orders.csv"
    PAPER_PNL_FILE: str = "paper_pnl.csv"

    # --- intervals/logging ---
    ANALYSIS_INTERVAL: int = 15
    INFO_LOG_INTERVAL_SEC: int = 300
    PERFORMANCE_ALERT_INTERVAL: int = 300

    # --- telegram/webhook ---
    BOT_TOKEN: str = ""
    ADMIN_CHAT_IDS: str = ""
    CHAT_ID: str = ""
    ENABLE_WEBHOOK: bool = True
    PUBLIC_URL: str = ""
    WEBHOOK_SECRET: str = ""
    TELEGRAM_SECRET_TOKEN: str = ""

    # --- web server ---
    WEB_CONCURRENCY: int = 1
    WEB_THREADS: int = 1

    # --- experimental ---
    CONTEXT_TIMEOUT_SEC: int = 6

    @classmethod
    def build(cls) -> "Settings":
        env = os.environ.get
        return cls(
            TZ=env("TZ") or "UTC",
            LOG_LEVEL=env("LOG_LEVEL") or "INFO",

            EXCHANGE_NAME=env("EXCHANGE_NAME") or "gateio",
            SYMBOL=env("SYMBOL") or "BTC/USDT",
            TIMEFRAME=env("TIMEFRAME") or "15m",
            OHLCV_LIMIT=_as_int(env("OHLCV_LIMIT"), 200),
            AGGREGATOR_LIMIT=_as_int(env("AGGREGATOR_LIMIT"), 200),
            ATR_PERIOD=_as_int(env("ATR_PERIOD"), 14),

            API_KEY=env("API_KEY") or env("GATE_API_KEY") or "",
            API_SECRET=env("API_SECRET") or env("GATE_API_SECRET") or "",
            GATE_API_KEY=env("GATE_API_KEY") or "",
            GATE_API_SECRET=env("GATE_API_SECRET") or "",

            ENABLE_TRADING=_as_bool(env("ENABLE_TRADING"), False),
            SAFE_MODE=_as_bool(env("SAFE_MODE"), True),
            PAPER_MODE=_as_bool(env("PAPER_MODE"), True),

            TRADE_AMOUNT=_as_float(env("TRADE_AMOUNT"), 10.0),
            MAX_CONCURRENT_POS=_as_int(env("MAX_CONCURRENT_POS"), 1),
            STOP_LOSS_PCT=_as_float(env("STOP_LOSS_PCT"), 2.0),
            TAKE_PROFIT_PCT=_as_float(env("TAKE_PROFIT_PCT"), 1.5),
            TRAILING_STOP_ENABLE=_as_bool(env("TRAILING_STOP_ENABLE"), True),
            TRAILING_STOP_PCT=_as_float(env("TRAILING_STOP_PCT"), 0.5),
            POST_SALE_COOLDOWN=_as_int(env("POST_SALE_COOLDOWN"), 60),

            TP1_PCT=_as_float(env("TP1_PCT"), 0.5),
            TP1_SIZE=_as_float(env("TP1_SIZE"), 0.25),
            TP2_PCT=_as_float(env("TP2_PCT"), 1.0),
            TP2_SIZE=_as_float(env("TP2_SIZE"), 0.25),
            TP3_PCT=_as_float(env("TP3_PCT"), 1.5),
            TP3_SIZE=_as_float(env("TP3_SIZE"), 0.25),
            TP4_PCT=_as_float(env("TP4_PCT"), 2.0),
            TP4_SIZE=_as_float(env("TP4_SIZE"), 0.25),

            MAX_CONSECUTIVE_LOSSES=_as_int(env("MAX_CONSECUTIVE_LOSSES"), 5),
            MIN_WIN_RATE=_as_int(env("MIN_WIN_RATE"), 35),
            NEGATIVE_SHARPE_LIMIT=_as_int(env("NEGATIVE_SHARPE_LIMIT"), 0),
            POOR_RR_THRESHOLD=_as_float(env("POOR_RR_THRESHOLD"), 0.5),
            DAILY_MAX_DRAWDOWN=_as_float(env("DAILY_MAX_DRAWDOWN"), 0.06),
            MAX_DRAWDOWN_PCT=_as_float(env("MAX_DRAWDOWN_PCT"), 15.0),

            MAX_SPREAD_BPS=_as_int(env("MAX_SPREAD_BPS"), 15),
            MIN_24H_VOLUME_USD=_as_float(env("MIN_24H_VOLUME_USD"), 1_000_000.0),
            TRADING_HOUR_START=_as_int(env("TRADING_HOUR_START"), 0),
            TRADING_HOUR_END=_as_int(env("TRADING_HOUR_END"), 24),

            AI_ENABLE=_as_bool(env("AI_ENABLE"), True),
            AI_FAILOVER_SCORE=_as_float(env("AI_FAILOVER_SCORE"), 0.55),
            AI_MIN_TO_TRADE=_as_float(env("AI_MIN_TO_TRADE"), 0.55),
            ENFORCE_AI_GATE=_as_bool(env("ENFORCE_AI_GATE"), True),
            MIN_SCORE_TO_BUY=_as_float(env("MIN_SCORE_TO_BUY"), 0.65),
            POSITION_MIN_FRACTION=_as_float(env("POSITION_MIN_FRACTION"), 0.30),
            POSITION_MAX_FRACTION=_as_float(env("POSITION_MAX_FRACTION"), 1.00),

            USE_CONTEXT_PENALTIES=_as_bool(env("USE_CONTEXT_PENALTIES"), False),
            CTX_BTC_DOM_ALTS_ONLY=_as_bool(env("CTX_BTC_DOM_ALTS_ONLY"), True),
            CTX_BTC_DOM_THRESH=_as_int(env("CTX_BTC_DOM_THRESH"), 52),
            CTX_BTC_DOM_PENALTY=_as_float(env("CTX_BTC_DOM_PENALTY"), -0.05),
            CTX_DXY_DELTA_THRESH=_as_float(env("CTX_DXY_DELTA_THRESH"), 0.5),
            CTX_DXY_PENALTY=_as_float(env("CTX_DXY_PENALTY"), -0.05),
            CTX_FNG_OVERHEATED=_as_int(env("CTX_FNG_OVERHEATED"), 75),
            CTX_FNG_UNDERSHOOT=_as_int(env("CTX_FNG_UNDERSHOOT"), 25),
            CTX_FNG_PENALTY=_as_float(env("CTX_FNG_PENALTY"), -0.05),
            CTX_FNG_BONUS=_as_float(env("CTX_FNG_BONUS"), 0.03),
            CTX_SCORE_CLAMP_MIN=_as_float(env("CTX_SCORE_CLAMP_MIN"), 0.0),
            CTX_SCORE_CLAMP_MAX=_as_float(env("CTX_SCORE_CLAMP_MAX"), 1.0),

            DATA_DIR=env("DATA_DIR") or "data",
            LOGS_DIR=env("LOGS_DIR") or "logs",
            MODEL_DIR=env("MODEL_DIR") or "models",
            CLOSED_TRADES_CSV=env("CLOSED_TRADES_CSV") or "closed_trades.csv",
            SIGNALS_CSV=env("SIGNALS_CSV") or "signals_snapshots.csv",
            PAPER_START_BALANCE_USD=_as_float(env("PAPER_START_BALANCE_USD"), 1000.0),
            PAPER_FEE_BPS=_as_int(env("PAPER_FEE_BPS"), 8),
            PAPER_SLIPPAGE_BPS=_as_int(env("PAPER_SLIPPAGE_BPS"), 10),
            PAPER_BALANCE_FILE=env("PAPER_BALANCE_FILE") or "paper_balance.json",
            PAPER_POSITIONS_FILE=env("PAPER_POSITIONS_FILE") or "paper_positions.json",
            PAPER_ORDERS_FILE=env("PAPER_ORDERS_FILE") or "paper_orders.csv",
            PAPER_PNL_FILE=env("PAPER_PNL_FILE") or "paper_pnl.csv",

            ANALYSIS_INTERVAL=_as_int(env("ANALYSIS_INTERVAL"), 15),
            INFO_LOG_INTERVAL_SEC=_as_int(env("INFO_LOG_INTERVAL_SEC"), 300),
            PERFORMANCE_ALERT_INTERVAL=_as_int(env("PERFORMANCE_ALERT_INTERVAL"), 300),

            BOT_TOKEN=env("BOT_TOKEN") or "",
            ADMIN_CHAT_IDS=env("ADMIN_CHAT_IDS") or "",
            CHAT_ID=env("CHAT_ID") or "",
            ENABLE_WEBHOOK=_as_bool(env("ENABLE_WEBHOOK"), True),
            PUBLIC_URL=env("PUBLIC_URL") or "",
            WEBHOOK_SECRET=env("WEBHOOK_SECRET") or "",
            TELEGRAM_SECRET_TOKEN=env("TELEGRAM_SECRET_TOKEN") or "",

            WEB_CONCURRENCY=_as_int(env("WEB_CONCURRENCY"), 1),
            WEB_THREADS=_as_int(env("WEB_THREADS"), 1),

            CONTEXT_TIMEOUT_SEC=_as_int(env("CONTEXT_TIMEOUT_SEC"), 6),
        )
