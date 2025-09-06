"""
Feature extraction pipeline for technical indicators.

Calculates technical indicators from OHLCV data for multiple timeframes.
Used by trading strategies for signal generation.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)


# -------- time helpers --------

def _to_utc_ts_ms(dt: datetime) -> int:
    """Return epoch milliseconds; if naive, assume UTC to avoid local-time drift."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


# -------- data types --------

@dataclass(frozen=True)
class Candle:
    """OHLCV candle data"""
    timestamp: datetime  # UTC timestamp (naive treated as UTC)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @property
    def t_ms(self) -> int:
        """Timestamp in milliseconds"""
        return _to_utc_ts_ms(self.timestamp)

    @property
    def o(self) -> float:
        """Open price as float (for compatibility)"""
        return float(self.open)

    @property
    def h(self) -> float:
        """High price as float"""
        return float(self.high)

    @property
    def l(self) -> float:
        """Low price as float"""
        return float(self.low)

    @property
    def c(self) -> float:
        """Close price as float"""
        return float(self.close)

    @property
    def v(self) -> float:
        """Volume as float"""
        return float(self.volume)


# -------- indicators --------

class TechnicalIndicators:
    """
    Technical indicators calculator.

    All indicators use standard parameters by default.
    Uses SMA seeding for EMA-based series to reduce initial bias.
    """

    # ------- moving averages -------

    @staticmethod
    def ema(values: list[float], period: int) -> Optional[float]:
        """
        Exponential Moving Average (SMA-seeded).

        Args:
            values: Price values (usually close prices)
            period: EMA period

        Returns:
            EMA value or None if not enough data
        """
        n = int(period)
        if n <= 0 or len(values) < n:
            return None

        # SMA seed
        seed = sum(values[:n]) / n
        k = 2.0 / (n + 1.0)
        ema_val = seed

        for x in values[n:]:
            ema_val = (x - ema_val) * k + ema_val

        return float(ema_val)

    @staticmethod
    def _ema_series(values: list[float], period: int) -> list[float]:
        """EMA series with SMA seeding; returns list aligned to full `values` length."""
        n = int(period)
        if n <= 0 or len(values) < n:
            return []
        seed = sum(values[:n]) / n
        k = 2.0 / (n + 1.0)
        out = [*([None] * (n - 1)), seed]  # pad until first EMA point
        ema_val = seed
        for x in values[n:]:
            ema_val = (x - ema_val) * k + ema_val
            out.append(ema_val)
        return out  # type: ignore[return-value]

    @staticmethod
    def sma(values: list[float], period: int) -> Optional[float]:
        """
        Simple Moving Average.

        Args:
            values: Price values
            period: SMA period

        Returns:
            SMA value or None if not enough data
        """
        n = int(period)
        if n <= 0 or len(values) < n:
            return None
        return sum(values[-n:]) / n

    # ------- momentum / volatility -------

    @staticmethod
    def rsi(values: list[float], period: int = 14) -> Optional[float]:
        """
        Relative Strength Index (Wilder's smoothing).

        Args:
            values: Price values (usually close prices)
            period: RSI period (default 14)

        Returns:
            RSI value (0-100) or None if not enough data
        """
        n = int(period)
        if n <= 0 or len(values) <= n:
            return None

        # Diffs
        gains: list[float] = []
        losses: list[float] = []
        for i in range(1, len(values)):
            diff = values[i] - values[i - 1]
            gains.append(max(0.0, diff))
            losses.append(max(0.0, -diff))

        # Initial averages over first n periods
        avg_gain = sum(gains[:n]) / n
        avg_loss = sum(losses[:n]) / n

        # Wilder smoothing
        for i in range(n, len(gains)):
            avg_gain = (avg_gain * (n - 1) + gains[i]) / n
            avg_loss = (avg_loss * (n - 1) + losses[i]) / n

        if avg_loss == 0:
            if avg_gain == 0:
                return 50.0
            return 100.0

        rs = avg_gain / avg_loss
        rsi_val = 100.0 - (100.0 / (1.0 + rs))
        return float(rsi_val)

    @staticmethod
    def atr(candles: list[Candle], period: int = 14) -> Optional[float]:
        """
        Average True Range (Wilder's smoothing).

        Args:
            candles: OHLCV candles
            period: ATR period (default 14)

        Returns:
            ATR value or None if not enough data
        """
        n = int(period)
        if n <= 0 or len(candles) < n + 1:
            return None

        # True ranges
        trs: list[float] = []
        prev_close = candles[0].c
        for c in candles[1:]:
            tr = max(
                c.h - c.l,
                abs(c.h - prev_close),
                abs(prev_close - c.l),
            )
            trs.append(tr)
            prev_close = c.c

        if len(trs) < n:
            return None

        # Initial ATR: mean of first n TRs
        atr_val = sum(trs[:n]) / n

        # Wilder smoothing over the rest
        for tr in trs[n:]:
            atr_val = (atr_val * (n - 1) + tr) / n

        return float(atr_val)

    # ------- MACD / Bands / Stoch -------

    @staticmethod
    def macd(
        values: list[float],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """
        MACD (Moving Average Convergence Divergence).

        Args:
            values: Price values (usually close prices)
            fast: Fast EMA period (default 12)
            slow: Slow EMA period (default 26)
            signal: Signal line EMA period (default 9)

        Returns:
            Tuple of (MACD line, Signal line, Histogram) or Nones
        """
        if slow <= 0 or fast <= 0 or signal <= 0:
            return None, None, None
        if len(values) < slow + signal:
            return None, None, None

        ema_fast = TechnicalIndicators._ema_series(values, fast)
        ema_slow = TechnicalIndicators._ema_series(values, slow)
        if not ema_fast or not ema_slow:
            return None, None, None

        # Align by index; compute macd only where both EMAs exist
        macd_series: list[float] = []
        for f, s in zip(ema_fast, ema_slow):
            if f is None or s is None:  # padded region
                continue
            macd_series.append(f - s)

        if len(macd_series) < signal:
            return None, None, None

        signal_series = TechnicalIndicators._ema_series(macd_series, signal)
        if not signal_series or signal_series[-1] is None:
            return None, None, None

        macd_val = macd_series[-1]
        signal_val = signal_series[-1]
        hist_val = macd_val - signal_val

        return float(macd_val), float(signal_val), float(hist_val)

    @staticmethod
    def bollinger_bands(
        values: list[float],
        period: int = 20,
        num_std: float = 2.0
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Bollinger Bands.

        Args:
            values: Price values (usually close prices)
            period: Moving average period (default 20)
            num_std: Number of standard deviations (default 2.0)

        Returns:
            Tuple of (Upper band, Middle band, Lower band) or Nones
        """
        n = int(period)
        if n <= 0 or len(values) < n:
            return None, None, None

        window = values[-n:]
        mean = sum(window) / n

        # Population stddev (as в большинстве библиотек TA)
        variance = sum((x - mean) ** 2 for x in window) / n
        std_dev = math.sqrt(variance)

        upper = mean + num_std * std_dev
        lower = mean - num_std * std_dev

        return float(upper), float(mean), float(lower)

    @staticmethod
    def stochastic(
        candles: list[Candle],
        k_period: int = 14,
        d_period: int = 3
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Stochastic Oscillator.

        Args:
            candles: OHLCV candles
            k_period: %K period (default 14)
            d_period: %D period (default 3)

        Returns:
            Tuple of (%K, %D) or Nones
        """
        k = int(k_period)
        d = int(d_period)
        if k <= 0 or d <= 0 or len(candles) < k + d:
            return None, None

        k_values: list[float] = []

        for i in range(k - 1, len(candles)):
            window = candles[i - k + 1 : i + 1]
            hi = max(c.h for c in window)
            lo = min(c.l for c in window)

            if hi == lo:
                k_val = 50.0  # Middle value when no range
            else:
                k_val = 100.0 * (candles[i].c - lo) / (hi - lo)

            k_values.append(k_val)

        if len(k_values) < d:
            return (k_values[-1] if k_values else None), None

        d_val = sum(k_values[-d:]) / d
        return float(k_values[-1]), float(d_val)


# -------- features pipeline --------

class FeaturePipeline:
    """
    Main feature extraction pipeline.

    Extracts technical indicators from multiple timeframes.
    """

    def __init__(self):
        """Initialize pipeline"""
        self.indicators = TechnicalIndicators()

    def extract_features(
        self,
        ohlcv_15m: Iterable[Candle],
        ohlcv_1h: Optional[Iterable[Candle]] = None,
        ohlcv_4h: Optional[Iterable[Candle]] = None,
        ohlcv_1d: Optional[Iterable[Candle]] = None,
        ohlcv_1w: Optional[Iterable[Candle]] = None,
    ) -> dict[str, float]:
        """
        Extract features from multi-timeframe OHLCV data.

        Args:
            ohlcv_15m: 15-minute candles (main trading timeframe)
            ohlcv_1h: 1-hour candles (optional)
            ohlcv_4h: 4-hour candles (optional)
            ohlcv_1d: Daily candles (optional)
            ohlcv_1w: Weekly candles (optional)

        Returns:
            Dictionary of features for ML/strategy use
        """
        features: dict[str, float] = {}

        # Process main timeframe (15m)
        candles_15m = list(ohlcv_15m or [])
        if candles_15m:
            features.update(self._extract_timeframe_features(candles_15m, "15m"))

        # Process higher timeframes for trend confirmation
        if ohlcv_1h:
            candles_1h = list(ohlcv_1h)
            if candles_1h:
                features.update(self._extract_timeframe_features(candles_1h, "1h"))

        if ohlcv_4h:
            candles_4h = list(ohlcv_4h)
            if candles_4h:
                features.update(self._extract_timeframe_features(candles_4h, "4h"))

        if ohlcv_1d:
            candles_1d = list(ohlcv_1d)
            if candles_1d:
                features.update(self._extract_timeframe_features(candles_1d, "1d"))

        if ohlcv_1w:
            candles_1w = list(ohlcv_1w)
            if candles_1w:
                features.update(self._extract_timeframe_features(candles_1w, "1w"))

        # Add cross-timeframe features
        features.update(self._extract_cross_timeframe_features(features))

        return features

    def _extract_timeframe_features(
        self,
        candles: list[Candle],
        timeframe: str
    ) -> dict[str, float]:
        """Extract features for a single timeframe"""
        if not candles:
            return {}

        close_prices = [c.c for c in candles]
        feats: dict[str, float] = {}

        # Price features
        feats[f"close_{timeframe}"] = float(close_prices[-1]) if close_prices else 0.0

        # Moving averages
        ema20 = self.indicators.ema(close_prices, 20)
        ema50 = self.indicators.ema(close_prices, 50)
        sma200 = self.indicators.sma(close_prices, 200)

        last_price = float(close_prices[-1]) if close_prices else 0.0
        feats[f"ema20_{timeframe}"] = float(ema20) if ema20 is not None else last_price
        feats[f"ema50_{timeframe}"] = float(ema50) if ema50 is not None else last_price
        feats[f"sma200_{timeframe}"] = float(sma200) if sma200 is not None else last_price

        # Momentum indicators
        rsi = self.indicators.rsi(close_prices, 14)
        feats[f"rsi14_{timeframe}"] = float(rsi) if rsi is not None else 50.0

        # MACD
        macd, signal, histogram = self.indicators.macd(close_prices)
        feats[f"macd_{timeframe}"] = float(macd) if macd is not None else 0.0
        feats[f"macd_signal_{timeframe}"] = float(signal) if signal is not None else 0.0
        feats[f"macd_hist_{timeframe}"] = float(histogram) if histogram is not None else 0.0

        # Volatility
        atr = self.indicators.atr(candles, 14)
        feats[f"atr14_{timeframe}"] = float(atr) if atr is not None else 0.0

        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = self.indicators.bollinger_bands(close_prices)
        feats[f"bb_upper_{timeframe}"] = float(bb_upper) if bb_upper is not None else last_price
        feats[f"bb_middle_{timeframe}"] = float(bb_middle) if bb_middle is not None else last_price
        feats[f"bb_lower_{timeframe}"] = float(bb_lower) if bb_lower is not None else last_price

        # Stochastic
        stoch_k, stoch_d = self.indicators.stochastic(candles)
        feats[f"stoch_k_{timeframe}"] = float(stoch_k) if stoch_k is not None else 50.0
        feats[f"stoch_d_{timeframe}"] = float(stoch_d) if stoch_d is not None else 50.0

        # Price position relative to bands/MAs
        if bb_upper is not None and bb_lower is not None and bb_upper != bb_lower:
            bb_position = (float(close_prices[-1]) - bb_lower) / (bb_upper - bb_lower)
            feats[f"bb_position_{timeframe}"] = max(0.0, min(1.0, float(bb_position)))

        # Trend strength
        if ema20 is not None and ema50 is not None and ema50 != 0:
            trend_strength = (ema20 - ema50) / ema50 * 100.0
            feats[f"trend_strength_{timeframe}"] = float(trend_strength)

        return feats

    def _extract_cross_timeframe_features(
        self,
        features: dict[str, float]
    ) -> dict[str, float]:
        """Extract features that compare multiple timeframes"""
        cross_features: dict[str, float] = {}

        # Trend alignment across timeframes
        timeframes = ["15m", "1h", "4h", "1d"]
        trend_scores: list[float] = []

        for tf in timeframes:
            ema20_key = f"ema20_{tf}"
            ema50_key = f"ema50_{tf}"

            if ema20_key in features and ema50_key in features:
                trend_scores.append(1.0 if features[ema20_key] > features[ema50_key] else -1.0)

        if trend_scores:
            cross_features["trend_alignment"] = sum(trend_scores) / len(trend_scores)

        # RSI divergence
        rsi_values: list[float] = []
        for tf in timeframes:
            rsi_key = f"rsi14_{tf}"
            if rsi_key in features:
                rsi_values.append(features[rsi_key])

        if len(rsi_values) >= 2:
            cross_features["rsi_divergence"] = max(rsi_values) - min(rsi_values)

        # Volatility ratio (short vs long term)
        if "atr14_15m" in features and "atr14_1d" in features and features["atr14_1d"] > 0:
            cross_features["volatility_ratio"] = features["atr14_15m"] / features["atr14_1d"]

        return cross_features


# Convenience function for backward compatibility
def last_features(
    ohlcv_15m: Iterable[Candle],
    ohlcv_1h: Optional[Iterable[Candle]] = None,
    ohlcv_4h: Optional[Iterable[Candle]] = None,
    ohlcv_1d: Optional[Iterable[Candle]] = None,
    ohlcv_1w: Optional[Iterable[Candle]] = None,
) -> dict[str, float]:
    """
    Extract features from OHLCV data (backward compatibility).

    This function maintains compatibility with existing code.
    """
    pipeline = FeaturePipeline()
    return pipeline.extract_features(
        ohlcv_15m=ohlcv_15m,
        ohlcv_1h=ohlcv_1h,
        ohlcv_4h=ohlcv_4h,
        ohlcv_1d=ohlcv_1d,
        ohlcv_1w=ohlcv_1w,
    )


# Export
__all__ = [
    "Candle",
    "TechnicalIndicators",
    "FeaturePipeline",
    "last_features",
]
