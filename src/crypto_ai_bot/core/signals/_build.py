# src/crypto_ai_bot/core/signals/_build.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Tuple

import pandas as pd

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.indicators import unified as I
from crypto_ai_bot.core.validators.dataframe import assert_min_len  # require_ohlcv (если есть)
from crypto_ai_bot.utils import metrics


def _to_df(ohlcv: list[list[float]]) -> pd.DataFrame:
    # ожидаем: [[ts, o, h, l, c, v], ...]
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    # упорядочим на всякий случай
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def _last_float(s: pd.Series, default: float | None = None) -> float | None:
    try:
        v = s.dropna().iloc[-1]
        return float(v)
    except Exception:
        return default


def _calc_indicators(df: pd.DataFrame, cfg) -> Dict[str, float | None]:
    # параметры по умолчанию
    ema_fast = int(getattr(cfg, "EMA_FAST", 20))
    ema_slow = int(getattr(cfg, "EMA_SLOW", 50))
    rsi_n = int(getattr(cfg, "RSI_N", 14))
    macd_fast = int(getattr(cfg, "MACD_FAST", 12))
    macd_slow = int(getattr(cfg, "MACD_SLOW", 26))
    macd_sig = int(getattr(cfg, "MACD_SIGNAL", 9))
    atr_n = int(getattr(cfg, "ATR_N", 14))

    ema_f = I.ema(df["close"], ema_fast)
    ema_s = I.ema(df["close"], ema_slow)
    rsi = I.rsi(df["close"], rsi_n)
    macd, macd_sig_s, macd_hist = I.macd(df["close"], macd_fast, macd_slow, macd_sig)
    atr = I.atr(df["high"], df["low"], df["close"], atr_n)

    close = df["close"]
    atr_pct = (atr / close) * 100.0

    return {
        "ema_fast": _last_float(ema_f),
        "ema_slow": _last_float(ema_s),
        "rsi": _last_float(rsi),
        "macd": _last_float(macd),
        "macd_signal": _last_float(macd_sig_s),
        "macd_hist": _last_float(macd_hist),
        "atr": _last_float(atr),
        "atr_pct": _last_float(atr_pct),
        "close": _last_float(close),
    }


def build(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """
    Сбор фич: OHLCV → индикаторы → нормализация → market/ticker (spread).
    Никаких HTTP/ENV — только вызовы брокера + чистые вычисления.
    """
    sym = normalize_symbol(symbol)
    tf = normalize_timeframe(timeframe)

    # 1) рыночные бары
    ohlcv = broker.fetch_ohlcv(sym, tf, int(limit))
    df = _to_df(ohlcv)
    min_bars = int(getattr(cfg, "MIN_FEATURE_BARS", 100))
    assert_min_len(df, min_bars)

    # 2) индикаторы
    feats = _calc_indicators(df, cfg)

    # 3) тикер для спреда/последней цены
    try:
        tkr = broker.fetch_ticker(sym)
        bid = float(tkr.get("bid") or tkr.get("last") or feats["close"] or 0.0)
        ask = float(tkr.get("ask") or tkr.get("last") or feats["close"] or 0.0)
        price = float(tkr.get("last") or feats["close"] or (bid + ask) / 2.0)
        spread_pct = float(((ask - bid) / price) * 100.0) if price > 0 else 0.0
    except Exception:
        # если тикер недоступен — используем close и нулевой спред
        bid = ask = price = float(feats["close"] or 0.0)
        spread_pct = 0.0

    metrics.inc("features_built_total", {"tf": tf})

    return {
        "indicators": {
            "ema_fast": feats["ema_fast"],
            "ema_slow": feats["ema_slow"],
            "rsi": feats["rsi"],
            "macd": feats["macd"],
            "macd_signal": feats["macd_signal"],
            "macd_hist": feats["macd_hist"],
            "atr": feats["atr"],
            "atr_pct": feats["atr_pct"],
        },
        "market": {
            "price": price,
            "bid": bid,
            "ask": ask,
            "spread_pct": spread_pct,
            "timeframe": tf,
            "symbol": sym,
        },
        "rule_score": None,  # может быть заполнен в policy при необходимости
        "ai_score": None,    # если ML блок подключится
    }
