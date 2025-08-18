# src/crypto_ai_bot/core/settings.py
from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional


class Settings:
    """
    Единый конфиг с поддержкой UPPER_CASE и snake_case алиасов.
    build() — из os.environ; from_reader() — из dict-like.
    """

    # ---- базовые поля и дефолты ----
    MODE: str = "paper"                  # paper | live | backtest
    EXCHANGE: str = "binance"
    SYMBOL: str = "BTC/USDT"
    TIMEFRAME: str = "1h"

    POSITION_SIZE_USD: float = 0.0
    FEE_TAKER_BPS: float = 20.0
    SLIPPAGE_BPS: float = 5.0

    IDEMPOTENCY_TTL_SEC: int = 300
    IDEMPOTENCY_BUCKET_MS: int = 5_000
    MAX_TIME_DRIFT_MS: int = 5_000

    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_BOT_SECRET: Optional[str] = None

    BACKTEST_CSV_PATH: Optional[str] = None
    BACKTEST_PRICES: Optional[list] = None
    BACKTEST_LAST_PRICE: float = 100.0

    PROFILE: Optional[str] = None
    ENV: Optional[str] = None

    _ALIASES: Dict[str, str] = {
        "mode": "MODE",
        "exchange": "EXCHANGE",
        "symbol": "SYMBOL",
        "timeframe": "TIMEFRAME",
        "position_size_usd": "POSITION_SIZE_USD",
        "fee_taker_bps": "FEE_TAKER_BPS",
        "slippage_bps": "SLIPPAGE_BPS",
        "idempotency_ttl_sec": "IDEMPOTENCY_TTL_SEC",
        "idempotency_bucket_ms": "IDEMPOTENCY_BUCKET_MS",
        "max_time_drift_ms": "MAX_TIME_DRIFT_MS",
        "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
        "telegram_bot_secret": "TELEGRAM_BOT_SECRET",
        "backtest_csv_path": "BACKTEST_CSV_PATH",
        "backtest_prices": "BACKTEST_PRICES",
        "backtest_last_price": "BACKTEST_LAST_PRICE",
        "profile": "PROFILE",
        "env": "ENV",
    }

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, self._normalize_key(k), v)

    @classmethod
    def from_reader(cls, env: Mapping[str, Any]) -> "Settings":
        """Строим Settings из dict-like. Поддерживает UPPER/snake и алиасы."""
        def _g(*names: str, default: Any = None, cast: Optional[type] = None):
            for n in names:
                if n in env and env[n] is not None:
                    return cast(env[n]) if cast else env[n]
                up = cls._ALIASES.get(n.lower())
                if up and up in env and env[up] is not None:
                    return cast(env[up]) if cast else env[up]
                if n.upper() in env and env[n.upper()] is not None:
                    return cast(env[n.upper()]) if cast else env[n.upper()]
            return default

        return cls(
            MODE=_g("MODE", "mode", default="paper", cast=str),
            EXCHANGE=_g("EXCHANGE", "exchange", default="binance", cast=str),
            SYMBOL=_g("SYMBOL", "symbol", default="BTC/USDT", cast=str),
            TIMEFRAME=_g("TIMEFRAME", "timeframe", default="1h", cast=str),
            POSITION_SIZE_USD=_g("POSITION_SIZE_USD", "position_size_usd", default=0.0, cast=float),
            FEE_TAKER_BPS=_g("FEE_TAKER_BPS", "fee_taker_bps", default=20.0, cast=float),
            SLIPPAGE_BPS=_g("SLIPPAGE_BPS", "slippage_bps", default=5.0, cast=float),
            IDEMPOTENCY_TTL_SEC=_g("IDEMPOTENCY_TTL_SEC", "idempotency_ttl_sec", default=300, cast=int),
            IDEMPOTENCY_BUCKET_MS=_g("IDEMPOTENCY_BUCKET_MS", "idempotency_bucket_ms", default=5000, cast=int),
            MAX_TIME_DRIFT_MS=_g("MAX_TIME_DRIFT_MS", "max_time_drift_ms", default=5000, cast=int),
            TELEGRAM_BOT_TOKEN=_g("TELEGRAM_BOT_TOKEN", "telegram_bot_token", default=None, cast=str),
            TELEGRAM_BOT_SECRET=_g("TELEGRAM_BOT_SECRET", "telegram_bot_secret", default=None, cast=str),
            BACKTEST_CSV_PATH=_g("BACKTEST_CSV_PATH", "backtest_csv_path", default=None, cast=str),
            BACKTEST_PRICES=_g("BACKTEST_PRICES", "backtest_prices", default=None),
            BACKTEST_LAST_PRICE=_g("BACKTEST_LAST_PRICE", "backtest_last_price", default=100.0, cast=float),
            PROFILE=_g("PROFILE", "profile", default=None, cast=str),
            ENV=_g("ENV", "env", default=None, cast=str),
        )

    @classmethod
    def build(cls) -> "Settings":
        return cls.from_reader(os.environ)

    @classmethod
    def _normalize_key(cls, k: str) -> str:
        if not k:
            return k
        if k in cls._ALIASES:
            return cls._ALIASES[k]
        if k.upper() in cls._ALIASES.values():
            return k.upper()
        return k

    def __getattr__(self, name: str) -> Any:
        if name in self._ALIASES:
            return getattr(self, self._ALIASES[name], None)
        raise AttributeError(name)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
