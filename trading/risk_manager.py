# trading/risk_manager.py
import logging
import os
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Tuple, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"

@dataclass
class RiskMetrics:
    volatility: float
    atr_normalized: float
    volume_ratio: float
    trend_strength: float
    market_condition: str
    risk_level: RiskLevel

class AdaptiveRiskManager:
    """
    Динамическое управление рисками с адаптивными стоп-лоссами и учетом рыночных условий
    """

    def __init__(self):
        # Параметры через .env (если нет — берём дефолты)
        self.volatility_lookback = int(os.getenv("VOLATILITY_LOOKBACK", 20))
        self.atr_period = int(os.getenv("ATR_PERIOD", 14))
        self.volume_lookback = int(os.getenv("VOLUME_LOOKBACK", 20))

        self.min_stop_pct = float(os.getenv("MIN_STOP_PCT", 0.005))  # 0.5%
        self.max_stop_pct = float(os.getenv("MAX_STOP_PCT", 0.05))   # 5%

        # Мультипликаторы
        self.risk_multipliers = {
            "STRONG_BULL": {"stop": 0.8, "volatility": 0.9},
            "WEAK_BULL": {"stop": 1.0, "volatility": 1.0},
            "SIDEWAYS": {"stop": 1.3, "volatility": 1.2},
            "WEAK_BEAR": {"stop": 1.1, "volatility": 1.1},
            "STRONG_BEAR": {"stop": 0.9, "volatility": 1.0}
        }

        # Границы риска
        self.risk_thresholds = {
            RiskLevel.LOW: {"vol": 0.02, "atr": 0.015},
            RiskLevel.MEDIUM: {"vol": 0.04, "atr": 0.03},
            RiskLevel.HIGH: {"vol": 0.06, "atr": 0.045},
            RiskLevel.EXTREME: {"vol": float("inf"), "atr": float("inf")}
        }

    def calculate_risk_metrics(self, df: pd.DataFrame, market_condition: str = "SIDEWAYS") -> RiskMetrics:
        """Расчет метрик риска"""
        if df.empty or len(df) < self.volatility_lookback:
            return self._default_risk_metrics()

        try:
            # Волатильность
            returns = df["close"].pct_change().dropna()
            volatility = returns.rolling(self.volatility_lookback).std().iloc[-1] or returns.std()

            # ATR
            atr = self._calculate_atr(df)
            atr_normalized = atr / df["close"].iloc[-1] if df["close"].iloc[-1] > 0 else 0.02

            # Объем
            volume_ma = df["volume"].rolling(self.volume_lookback).mean()
            current_volume = df["volume"].iloc[-1]
            volume_ratio = current_volume / volume_ma.iloc[-1] if volume_ma.iloc[-1] > 0 else 1.0

            # Тренд
            ema_20 = df["close"].ewm(span=20).mean()
            trend_strength = self._calculate_trend_strength(ema_20)

            # Уровень риска
            risk_level = self._determine_risk_level(volatility, atr_normalized)

            return RiskMetrics(
                volatility=float(volatility),
                atr_normalized=float(atr_normalized),
                volume_ratio=float(volume_ratio),
                trend_strength=float(trend_strength),
                market_condition=market_condition,
                risk_level=risk_level
            )

        except Exception as e:
            logging.error(f"Risk metrics error: {e}")
            return self._default_risk_metrics()

    def calculate_dynamic_stop_loss(self, entry_price: float, df: pd.DataFrame, market_condition: str = "SIDEWAYS") -> Tuple[float, Dict[str, Any]]:
        """Динамический стоп-лосс"""
        risk_metrics = self.calculate_risk_metrics(df, market_condition)

        atr = self._calculate_atr(df)
        base_atr_stop = entry_price - (atr * 1.5)

        volatility_multiplier = 1 + (risk_metrics.volatility * 5)
        market_multiplier = self.risk_multipliers.get(market_condition, {"stop": 1.0})["stop"]
        volume_multiplier = 1 / (1 + max(0, risk_metrics.volume_ratio - 1) * 0.3)

        combined_multiplier = volatility_multiplier * market_multiplier * volume_multiplier
        dynamic_stop = entry_price - (atr * 1.5 * combined_multiplier)

        min_stop = entry_price * (1 - self.min_stop_pct)
        max_stop = entry_price * (1 - self.max_stop_pct)
        final_stop = max(min_stop, min(dynamic_stop, max_stop))

        details = {
            "base_atr_stop": base_atr_stop,
            "atr_value": atr,
            "volatility": risk_metrics.volatility,
            "volatility_multiplier": volatility_multiplier,
            "market_multiplier": market_multiplier,
            "volume_multiplier": volume_multiplier,
            "combined_multiplier": combined_multiplier,
            "risk_level": risk_metrics.risk_level.value,
            "final_stop_pct": round((entry_price - final_stop) / entry_price * 100, 2)
        }

        logging.info(f"🛡️ Dynamic SL: {final_stop:.6f} | Details: {details}")
        return final_stop, details

    # --- вспомогательные методы ---
    def _calculate_atr(self, df: pd.DataFrame, period: Optional[int] = None) -> float:
        """ATR"""
        period = period or self.atr_period
        if len(df) < period + 1:
            return df["close"].iloc[-1] * 0.02
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - df["close"].shift(1)).abs()
        tr3 = (df["low"] - df["close"].shift(1)).abs()
        atr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(window=period).mean().iloc[-1]
        return float(atr) if pd.notna(atr) else df["close"].iloc[-1] * 0.02

    def _calculate_trend_strength(self, ema_series: pd.Series) -> float:
        """Сила тренда"""
        if len(ema_series) < 5:
            return 0.0
        x = np.arange(5)
        y = ema_series.iloc[-5:].values
        if len(y) < 5:
            return 0.0
        try:
            slope = np.polyfit(x, y, 1)[0]
            return float(np.clip((slope / y[-1]) * 1000, -1, 1))
        except:
            return 0.0

    def _determine_risk_level(self, volatility: float, atr_normalized: float) -> RiskLevel:
        """Определение уровня риска"""
        for level, t in self.risk_thresholds.items():
            if volatility <= t["vol"] and atr_normalized <= t["atr"]:
                return level
        return RiskLevel.EXTREME

    def _default_risk_metrics(self) -> RiskMetrics:
        """Метрики по умолчанию"""
        return RiskMetrics(
            volatility=0.03,
            atr_normalized=0.02,
            volume_ratio=1.0,
            trend_strength=0.0,
            market_condition="SIDEWAYS",
            risk_level=RiskLevel.MEDIUM
        )