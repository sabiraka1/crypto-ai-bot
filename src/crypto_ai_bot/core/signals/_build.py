from __future__ import annotations

from typing import Dict, Any, Tuple, Optional
from decimal import Decimal
from datetime import datetime, timezone

import pandas as pd  # runtime dep ensured in requirements
import numpy as np

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.indicators import unified as IND

# ---- helpers -----------------------------------------------------------------

def _safe_last(series: pd.Series, default: float = float("nan")) -> float:
    try:
        return float(series.iloc[-1])
    except Exception:
        return default

def _compute_spread_pct(ticker: Dict[str, Any]) -> Optional[float]:
    try:
        bid = float(ticker.get("bid"))
        ask = float(ticker.get("ask"))
        if bid > 0 and ask > 0 and ask >= bid:
            mid = 0.5 * (ask + bid)
            if mid > 0:
                return (ask - bid) / mid * 100.0
    except Exception:
        pass
    return None

def _ensure_min_len(df: pd.DataFrame, n: int) -> bool:
    try:
        return len(df) >= n
    except Exception:
        return False

# ---- public (internal) API ---------------------------------------------------

def build(cfg, broker, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    """Собирает feature-set: OHLCV → индикаторы → normalize → context.
    Без обращения к БД. Только broker + векторные индикаторы.
    Возвращает dict со структурой, пригодной для policy/fusion/risk.
    """
    sym = normalize_symbol(symbol or cfg.SYMBOL)
    tf = normalize_timeframe(timeframe or cfg.TIMEFRAME)

    # Fetch OHLCV
    raw = broker.fetch_ohlcv(sym, tf, limit)  # [[ts, o, h, l, c, v], ...]
    if not raw or len(raw) < 50:
        raise ValueError("not_enough_ohlcv")

    df = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume"])
    # normalize types
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    for col in ("open","high","low","close","volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Indicators (centralized in IND)
    # Use common defaults
    ema_fast_n, ema_slow_n = 20, 50
    rsi_n = 14
    macd_fast, macd_slow, macd_signal = 12, 26, 9
    atr_n = 14

    ema_fast = IND.ema(df["close"], ema_fast_n)
    ema_slow = IND.ema(df["close"], ema_slow_n)
    rsi = IND.rsi(df["close"], rsi_n)
    macd_line, macd_signal_s, macd_hist = IND.macd(df["close"], macd_fast, macd_slow, macd_signal)
    atr = IND.atr(df["high"], df["low"], df["close"], atr_n)

    # Aggregate last values
    last_close = _safe_last(df["close"])
    last_ts = df["ts"].iloc[-1].to_pydatetime().replace(tzinfo=timezone.utc)

    atr_pct = float("nan")
    if last_close and last_close > 0 and _ensure_min_len(atr, atr_n):
        atr_pct = float(_safe_last(atr) / last_close * 100.0)

    # Ticker/spread
    ticker = {}
    try:
        ticker = broker.fetch_ticker(sym) or {}
    except Exception:
        ticker = {}

    spread_pct = _compute_spread_pct(ticker)

    # Context
    ctx = {
        "hour": last_ts.hour,                         # UTC hour of last candle
        "spread_pct": spread_pct,                     # None if bid/ask unknown
        "price": float(last_close),
        "ts": int(last_ts.timestamp() * 1000),
        # optional fields (left None for now; can be filled by higher layers)
        "day_drawdown_pct": None,
        "seq_losses": None,
        "exposure_pct": None,
        "exposure_usd": None,
    }

    features = {
        "symbol": sym,
        "timeframe": tf,
        "indicators": {
            "ema_fast": float(_safe_last(ema_fast)),
            "ema_slow": float(_safe_last(ema_slow)),
            "rsi": float(_safe_last(rsi)),
            "macd_hist": float(_safe_last(macd_hist)),
            "atr": float(_safe_last(atr)),
            "atr_pct": float(atr_pct),
        },
        "market": {
            "price": float(last_close),
            "ts": int(last_ts.timestamp() * 1000),
        },
        "context": ctx,
        # placeholders for scoring layers (policy/_fusion will use them)
        "rule_score": None,
        "ai_score": None,
    }

    return features
