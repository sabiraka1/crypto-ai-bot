# analysis/market_analyzer.py

import logging
from typing import Tuple

import numpy as np
import pandas as pd

from config.settings import MarketCondition

_EPS = 1e-12


class MultiTimeframeAnalyzer:
    """Анализ рынка на двух ТФ (1D и 4H). Возвращает (MarketCondition, confidence)."""

    def __init__(self):
        # веса ТФ
        self._w_daily = 0.6
        self._w_h4 = 0.4
        # параметры
        self._ema_fast = 20
        self._ema_slow = 50
        self._momentum_lookback = 20
        self._vol_window = 60
        self._atr_period = 14

    # ---------- public ----------
    def analyze_market_condition(self, df_1d: pd.DataFrame, df_4h: pd.DataFrame) -> Tuple[MarketCondition, float]:
        try:
            td = self._trend(df_1d)
            sd = self._strength(df_1d)
            th = self._trend(df_4h)
            sh = self._strength(df_4h)

            combined_trend = float(self._w_daily * td + self._w_h4 * th)
            combined_strength = float(self._w_daily * sd + self._w_h4 * sh)

            condition = self._classify(combined_trend, combined_strength)
            confidence = float(np.clip(abs(combined_trend) * combined_strength, 0.0, 1.0))

            logging.info(f"📊 Market Analysis: {condition.value}, Confidence: {confidence:.2f}")
            return condition, confidence
        except Exception as e:
            logging.exception(f"Market analysis failed: {e}")
            return MarketCondition.SIDEWAYS, 0.10

    # ---------- internals ----------
    def _trend(self, df: pd.DataFrame) -> float:
        """Направление тренда в [-1..1]. Устойчиво к коротким сериям."""
        if df is None or df.empty or "close" not in df or "volume" not in df:
            return 0.0

        close = df["close"].astype("float64")
        volume = df["volume"].astype("float64")

        ema_fast = close.ewm(span=self._ema_fast, adjust=False, min_periods=1).mean()
        ema_slow = close.ewm(span=self._ema_slow, adjust=False, min_periods=1).mean()

        ema_trend = (ema_fast.iloc[-1] - ema_slow.iloc[-1]) / (abs(ema_slow.iloc[-1]) + _EPS)

        lb = min(self._momentum_lookback, max(1, len(close) - 1))
        mom_den = abs(close.iloc[-lb]) + _EPS
        price_momentum = (close.iloc[-1] - close.iloc[-lb]) / mom_den

        v_ma = volume.rolling(window=20, min_periods=5).mean()
        recent = v_ma.iloc[-5:].mean() if v_ma.notna().any() else 0.0
        older = v_ma.iloc[-25:-5].mean() if len(v_ma) >= 25 else (v_ma.iloc[:max(1, len(v_ma) - 5)].mean() if len(v_ma) > 5 else 0.0)
        volume_trend = (recent - older) / (abs(older) + _EPS)

        trend = 0.4 * ema_trend + 0.4 * price_momentum + 0.2 * volume_trend
        return float(np.clip(trend, -1.0, 1.0))

    def _strength(self, df: pd.DataFrame) -> float:
        """Сила тренда в [0..1]. Ниже волатильность — выше сила; ATR нормализуем ценой."""
        if df is None or df.empty or "close" not in df or "high" not in df or "low" not in df:
            return 0.5

        close = df["close"].astype("float64")
        high = df["high"].astype("float64")
        low = df["low"].astype("float64")

        # волатильность доходностей
        ret = close.pct_change().dropna()
        vol = float(ret.rolling(window=min(self._vol_window, max(5, len(ret)))).std().iloc[-1]) if len(ret) >= 5 else float(ret.std() or 0.0)
        vol = max(0.0, vol)

        # ATR (True Range)
        prev_close = close.shift(1)
        tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        from analysis.technical_indicators import _atr_series_for_ml
	temp_df = pd.DataFrame({'high': high, 'low': low, 'close': close})
	atr = _atr_series_for_ml(temp_df, self._atr_period)
        atr_norm = float((atr.iloc[-1] / (abs(close.iloc[-1]) + _EPS)) if atr.notna().any() else 0.0)

        # сглажённая метрика силы: ниже vol/atr_norm -> выше сила
        # параметры подобраны, чтобы диапазон был ~[0.2..0.9] для реальных рынков
        strength = 1.0 / (1.0 + 120.0 * vol + 15.0 * atr_norm)
        return float(np.clip(strength, 0.0, 1.0))

    def _classify(self, trend: float, strength: float) -> MarketCondition:
        if trend > 0.10 and strength > 0.70:
            return MarketCondition.STRONG_BULL
        if trend > 0.05 and strength > 0.50:
            return MarketCondition.WEAK_BULL
        if trend < -0.10 and strength > 0.70:
            return MarketCondition.STRONG_BEAR
        if trend < -0.05 and strength > 0.50:
            return MarketCondition.WEAK_BEAR
        return MarketCondition.SIDEWAYS
