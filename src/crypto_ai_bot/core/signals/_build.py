from __future__ import annotations

from typing import Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime, timezone

import pandas as pd

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.indicators import unified as ind
from crypto_ai_bot.core.validators.dataframe import require_ohlcv


def _to_utc(ts_ms: int) -> datetime:
    # безопасная конверсия миллисекунд в UTC-aware datetime
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)


def _prep_dataframe(ohlcv: list[list[float]]) -> pd.DataFrame:
    """
    Превращаем OHLCV массив в DataFrame стандарта: [ts, open, high, low, close, volume]
    """
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    df = require_ohlcv(df)
    return df


def _calc_indicators(df: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """
    Возвращает:
      - indicators: плоский словарь с основными сигналами
      - market: текущий срез рынка (price/ts)
    """
    closes = df["close"]
    highs = df["high"]
    lows = df["low"]

    # Базовый набор: EMA(20/50), RSI(14), MACD, ATR(14) + ATR в процентах
    ema20 = ind.ema(closes, 20).iloc[-1]
    ema50 = ind.ema(closes, 50).iloc[-1]
    rsi14 = ind.rsi(closes, 14).iloc[-1]

    macd_line, macd_signal, macd_hist = ind.macd(closes)  # дефолты (12,26,9)
    macd_hist_last = macd_hist.iloc[-1]

    atr14 = ind.atr(highs, lows, closes, 14).iloc[-1]
    price = float(closes.iloc[-1])
    atr_pct = float(atr14) / price if price != 0 else 0.0

    indicators = {
        "ema_fast": float(ema20),
        "ema_slow": float(ema50),
        "rsi": float(rsi14),
        "macd_hist": float(macd_hist_last),
        "atr": float(atr14),
        "atr_pct": float(atr_pct),
    }

    market = {
        "price": Decimal(str(price)),
        "ts": _to_utc(int(df["ts"].iloc[-1])),
    }

    return indicators, market


def build(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    Приватный билдер фич: OHLCV → индикаторы → нормализация.
    Никаких HTTP/ENV/БД. Только broker.fetch_ohlcv().
    """
    sym = normalize_symbol(symbol)
    tf = normalize_timeframe(timeframe)

    # 1) Загружаем OHLCV
    ohlcv = broker.fetch_ohlcv(sym, tf, limit)
    df = _prep_dataframe(ohlcv)

    # 2) Индикаторы + рыночный срез
    indicators, market = _calc_indicators(df)

    # 3) Контекст для risk-правил (bars — критично для check_min_history)
    context = {
        "bars": int(len(df)),
        # "exposure":  None,   # можно проложить позже из PositionTracker при желании
        # "time_drift_ms": None,  # жёсткий стоп по drift делаем в policy/health
    }

    features: Dict[str, Any] = {
        "indicators": indicators,
        "market": market,
        "context": context,
        "rule_score": None,
        "ai_score": None,
    }
    return features
