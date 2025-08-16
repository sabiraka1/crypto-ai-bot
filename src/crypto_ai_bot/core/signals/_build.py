# src/crypto_ai_bot/core/signals/_build.py
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.validators.dataframe import require_ohlcv, assert_min_len
from crypto_ai_bot.core.indicators import unified as ind


def _to_df(ohlcv: list[list[float]]) -> pd.DataFrame:
    """
    Преобразует CCXT-совместимый OHLCV в DataFrame с каноническими колонками.
    ohlcv: [[ts_ms, open, high, low, close, volume], ...]
    """
    if not ohlcv:
        raise ValueError("empty OHLCV")
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    # ts → UTC datetime (но для индикаторов удобно держать как ms; конвертим только для "market" блока)
    return require_ohlcv(df)


def _indicators(df: pd.DataFrame) -> Dict[str, float]:
    """Вычисляет базовые индикаторы на последней свече."""
    assert_min_len(df, 50)  # безопасный минимум для EMA50/MACD
    close = df["close"]
    high, low = df["high"], df["low"]

    ema20 = float(ind.ema(close, 20).iloc[-1])
    ema50 = float(ind.ema(close, 50).iloc[-1])
    rsi14 = float(ind.rsi(close, 14).iloc[-1])

    macd_line, macd_signal, macd_hist = ind.macd(close)  # дефолт: 12/26/9
    macd_hist_last = float(macd_hist.iloc[-1])

    atr14 = float(ind.atr(high, low, close, 14).iloc[-1])
    price = float(close.iloc[-1])
    atr_pct = float(atr14 / price * 100.0)*_
