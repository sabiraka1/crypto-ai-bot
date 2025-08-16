# src/crypto_ai_bot/core/signals/_build.py
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict

import pandas as pd

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.validators import require_ohlcv_min
from crypto_ai_bot.core.indicators.unified import ema, rsi, macd, atr


def _last_ts_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()


def build(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    1) Нормализация symbol/timeframe (единые правила).
    2) Забираем OHLCV у брокера.
    3) Приводим к канону и минимуму длины.
    4) Считаем индикаторы (только через unified).
    5) Готовим стабильную структуру features.
    """
    sym = normalize_symbol(symbol)
    tf = normalize_timeframe(timeframe)

    rows = broker.fetch_ohlcv(sym, tf, int(limit))
    df = require_ohlcv_min(rows, min_len=int(getattr(cfg, "MIN_FEATURE_BARS", 100)))

    # Индикаторы (векторные)
    close = pd.Series(df["close"].to_numpy(), copy=False)
    high = pd.Series(df["high"].to_numpy(), copy=False)
    low = pd.Series(df["low"].to_numpy(), copy=False)

    ema20 = ema(close, 20).iloc[-1]
    ema50 = ema(close, 50).iloc[-1]
    rsi14 = rsi(close, 14).iloc[-1]
    macd_line, macd_signal, macd_hist = macd(close, 12, 26, 9)
    macd_hist_last = macd_hist.iloc[-1]

    atr14 = atr(high, low, close, 14).iloc[-1]
    last_close = Decimal(str(df["close"].iloc[-1]))
    atr_pct = float((Decimal(str(atr14)) / (last_close if last_close != 0 else Decimal("1"))) * 100)

    features = {
        "indicators": {
            "ema20": float(ema20),
            "ema50": float(ema50),
            "rsi14": float(rsi14),
            "macd_hist": float(macd_hist_last),
            "atr": float(atr14),
            "atr_pct": float(atr_pct),
        },
        "market": {
            "symbol": sym,
            "timeframe": tf,
            "ts": _last_ts_iso(int(df["ts"].iloc[-1])),
            "price": last_close,  # Decimal
        },
        # Доп. источники скоринга можно проставлять выше по стэку:
        "rule_score": None,
        "ai_score": None,
    }

    return features
