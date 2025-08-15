# -*- coding: utf-8 -*-
# src/crypto_ai_bot/trading/risk_manager.py
"""
ğŸ›¡ï¸ RiskManager â€” ÑƒĞ½Ğ¸Ñ„Ğ¸Ñ†Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğ¹ Ñ€Ğ¸ÑĞº-Ğ¼ĞµĞ½ĞµĞ´Ğ¶ĞµÑ€ (Ğ±ĞµĞ· Ğ»Ğ¾ĞºĞ°Ğ»ÑŒĞ½Ñ‹Ñ… Ğ´ÑƒĞ±Ğ»ĞµĞ¹ ATR/EMA)
Ğ¡Ğ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼ Ñ Ñ‚ĞµĞºÑƒÑ‰ĞµĞ¹ Ğ°Ñ€Ñ…Ğ¸Ñ‚ĞµĞºÑ‚ÑƒÑ€Ğ¾Ğ¹ (Settings, Bot).

ĞÑĞ¾Ğ±ĞµĞ½Ğ½Ğ¾ÑÑ‚Ğ¸:
- ATR Ñ‡ĞµÑ€ĞµĞ· crypto_ai_bot.core.indicators.unified.atr_last (Ğ½Ğ¸ĞºĞ°ĞºĞ¸Ñ… Ğ»Ğ¾ĞºĞ°Ğ»ÑŒĞ½Ñ‹Ñ… Ñ€ĞµĞ°Ğ»Ğ¸Ğ·Ğ°Ñ†Ğ¸Ğ¹)
- ĞŸĞ¾Ñ€Ğ¾Ğ³Ğ¾Ğ²Ñ‹Ğµ Ğ½Ğ°ÑÑ‚Ñ€Ğ¾Ğ¹ĞºĞ¸ Ñ‡Ğ¸Ñ‚Ğ°ÑÑ‚ÑÑ Ğ¸Ğ· Settings (Ñ Ğ´ĞµÑ„Ğ¾Ğ»Ñ‚Ğ°Ğ¼Ğ¸)
- ĞœĞµÑ‚Ñ€Ğ¸ĞºĞ¸ Ñ€Ğ¸ÑĞºĞ°: Ğ²Ğ¾Ğ»Ğ°Ñ‚Ğ¸Ğ»ÑŒĞ½Ğ¾ÑÑ‚ÑŒ, Ğ½Ğ¾Ñ€Ğ¼Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğ¹ ATR, Ğ¾Ğ±ÑŠÑ‘Ğ¼, ÑĞ¸Ğ»Ğ° Ñ‚Ñ€ĞµĞ½Ğ´Ğ°
- Ğ”Ğ¸Ğ½Ğ°Ğ¼Ğ¸Ñ‡ĞµÑĞºĞ¸Ğ¹ ÑÑ‚Ğ¾Ğ¿-Ğ»Ğ¾ÑÑ Ñ ÑƒÑ‡Ñ‘Ñ‚Ğ¾Ğ¼ Ñ€ĞµĞ¶Ğ¸Ğ¼Ğ° Ñ€Ñ‹Ğ½ĞºĞ° Ğ¸ Ğ³Ñ€Ğ°Ğ½Ğ¸Ñ† Ğ¿Ñ€Ğ¾Ñ†ĞµĞ½Ñ‚Ğ¾Ğ²
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, Tuple, List

import numpy as np
import pandas as pd

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.indicators import unified as I

logger = logging.getLogger(__name__)

# â”€â”€ Ğ¢Ğ¸Ğ¿Ñ‹/ÑÑ‚Ñ€ÑƒĞºÑ‚ÑƒÑ€Ñ‹ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


@dataclass
class RiskMetrics:
    volatility: float          # std(pct_change) Ğ·Ğ° Ğ¾ĞºĞ½Ğ¾
    atr_normalized: float      # ATR / close
    volume_ratio: float        # vol / SMA(vol, N)
    trend_strength: float      # Ğ½Ğ¾Ñ€Ğ¼Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğ¹ Ğ½Ğ°ĞºĞ»Ğ¾Ğ½ EMA20
    market_condition: str      # STRONG_BULL/WEAK_BULL/SIDEWAYS/WEAK_BEAR/STRONG_BEAR
    risk_level: RiskLevel


# â”€â”€ Ğ’ÑĞ¿Ğ¾Ğ¼Ğ¾Ğ³Ğ°Ñ‚ĞµĞ»ÑŒĞ½Ñ‹Ğµ Ğ²Ñ‹Ñ‡Ğ¸ÑĞ»ĞµĞ½Ğ¸Ñ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _trend_strength_from_ema20(close: pd.Series) -> float:
    """ĞĞ¾Ñ€Ğ¼Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğ¹ Ğ½Ğ°ĞºĞ»Ğ¾Ğ½ EMA20 Ğ·Ğ° 5 Ğ¿Ğ¾ÑĞ»ĞµĞ´Ğ½Ğ¸Ñ… Ñ‚Ğ¾Ñ‡ĞµĞº ([-1..1])."""
    if close is None or len(close) < 25:
        return 0.0
    ema20 = I.ema(close, 20)
    if len(ema20) < 5:
        return 0.0
    y = ema20.iloc[-5:].values
    if not np.all(np.isfinite(y)):
        return 0.0
    x = np.arange(5, dtype=float)
    slope = np.polyfit(x, y, 1)[0]
    try:
        return float(np.clip((slope / y[-1]) * 1000.0, -1.0, 1.0))
    except Exception:
        return 0.0


# â”€â”€ ĞšĞ»Ğ°ÑÑ RiskManager â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class RiskManager:
    """
    Ğ£Ğ½Ğ¸Ñ„Ğ¸Ñ†Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğ¹ Ñ€Ğ¸ÑĞº-Ğ¼ĞµĞ½ĞµĞ´Ğ¶ĞµÑ€:
      - get_unified_atr(df)
      - calculate_risk_metrics(df, market_condition)
      - calculate_dynamic_stop_loss(entry_price, df, market_condition)
      - get_status_summary()
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.cfg = settings or Settings()  # Ğ´Ğ¾Ğ¿ÑƒÑĞºĞ°ĞµĞ¼ Ğ²Ñ‹Ğ·Ğ¾Ğ² Ğ±ĞµĞ· DI
        # Ğ‘Ğ°Ğ·Ğ¾Ğ²Ñ‹Ğµ Ğ½Ğ°ÑÑ‚Ñ€Ğ¾Ğ¹ĞºĞ¸ (ÑĞ¸Ğ½Ñ…Ñ€Ğ¾Ğ½Ğ¸Ğ·Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ñ‹ Ğ¿Ğ¾ Ğ´ÑƒÑ…Ñƒ Ñ Ğ²Ğ°Ğ»Ğ¸Ğ´Ğ°Ñ‚Ğ¾Ñ€Ğ¾Ğ¼/entry)
        self.atr_period: int = int(getattr(self.cfg, "ATR_PERIOD", 14))
        self.atr_method: str = str(getattr(self.cfg, "RISK_ATR_METHOD", "ewm")).lower()
        self.atr_compare_enabled: bool = bool(getattr(self.cfg, "RISK_ATR_COMPARE", False))

        # Ğ“Ñ€Ğ°Ğ½Ğ¸Ñ†Ñ‹ ÑÑ‚Ğ¾Ğ¿Ğ° (Ğ² Ğ´Ğ¾Ğ»ÑÑ… Ñ†ĞµĞ½Ñ‹): 0.5%..5% Ğ¿Ğ¾ ÑƒĞ¼Ğ¾Ğ»Ñ‡Ğ°Ğ½Ğ¸Ñ
        self.min_stop_pct: float = float(getattr(self.cfg, "MIN_STOP_PCT", 0.005))
        self.max_stop_pct: float = float(getattr(self.cfg, "MAX_STOP_PCT", 0.05))

        # ĞĞºĞ½Ğ° Ğ´Ğ»Ñ Ğ¼ĞµÑ‚Ñ€Ğ¸Ğº
        self.volatility_lookback: int = int(getattr(self.cfg, "VOLATILITY_LOOKBACK", 20))
        self.volume_lookback: int = int(getattr(self.cfg, "VOLUME_LOOKBACK", 20))

        # ĞšĞ°Ñ€Ñ‚Ğ° Ğ¼ÑƒĞ»ÑŒÑ‚Ğ¸Ğ¿Ğ»Ğ¸ĞºĞ°Ñ‚Ğ¾Ñ€Ğ¾Ğ² Ğ¿Ğ¾ Â«Ñ€ĞµĞ¶Ğ¸Ğ¼Ñƒ Ñ€Ñ‹Ğ½ĞºĞ°Â»
        self.risk_multipliers: Dict[str, Dict[str, float]] = {
            "STRONG_BULL": {"stop": 0.85, "volatility": 0.9},
            "WEAK_BULL":   {"stop": 1.00, "volatility": 1.0},
            "SIDEWAYS":    {"stop": 1.25, "volatility": 1.15},
            "WEAK_BEAR":   {"stop": 1.10, "volatility": 1.05},
            "STRONG_BEAR": {"stop": 0.95, "volatility": 1.00},
        }

        # ĞŸĞ¾Ñ€Ğ¾Ğ³Ğ¾Ğ²Ñ‹Ğµ ÑƒÑ€Ğ¾Ğ²Ğ½Ğ¸ Ñ€Ğ¸ÑĞºĞ° (Ğ²Ğ¾Ğ»Ğ°/ATR_norm)
        self.risk_thresholds: Dict[RiskLevel, Dict[str, float]] = {
            RiskLevel.LOW:     {"vol": 0.02, "atr": 0.015},
            RiskLevel.MEDIUM:  {"vol": 0.04, "atr": 0.030},
            RiskLevel.HIGH:    {"vol": 0.06, "atr": 0.045},
            RiskLevel.EXTREME: {"vol": float("inf"), "atr": float("inf")},
        }

        # Ğ”Ğ¸Ğ°Ğ³Ğ½Ğ¾ÑÑ‚Ğ¸ĞºĞ°
        self._stats: Dict[str, Any] = {
            "total_calculations": 0,
            "unified_atr_calls": 0,
        }
        logger.info(f"ğŸ›¡ï¸ RiskManager ready (ATR period={self.atr_period}, method={self.atr_method})")

    # â”€â”€ ATR â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def get_unified_atr(self, df: pd.DataFrame, period: Optional[int] = None) -> float:
        """
        Ğ£Ğ½Ğ¸Ñ„Ğ¸Ñ†Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğ¹ ATR (Ñ‡ĞµÑ€ĞµĞ· core.indicators.unified.atr_last).
        Ğ‘ĞµĞ· Ğ»Ğ¾ĞºĞ°Ğ»ÑŒĞ½Ñ‹Ñ… Ñ€ĞµĞ°Ğ»Ğ¸Ğ·Ğ°Ñ†Ğ¸Ğ¹, Ñ‡Ñ‚Ğ¾Ğ±Ñ‹ Ğ½Ğµ Ğ¿Ğ»Ğ¾Ğ´Ğ¸Ñ‚ÑŒ Ğ´ÑƒĞ±Ğ»Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ¸Ğµ.
        """
        if df is None or df.empty:
            return float("nan")
        p = int(period or self.atr_period)
        try:
            h = df["high"].astype("float64")
            l = df["low"].astype("float64")
            c = df["close"].astype("float64")
            val = I.atr_last(h, l, c, period=p)
            self._stats["unified_atr_calls"] += 1
            return float(val)
        except Exception as e:  # pragma: no cover
            logger.warning(f"ATR compute failed: {e!r}")
            return float("nan")

    # â”€â”€ ĞœĞµÑ‚Ñ€Ğ¸ĞºĞ¸ Ñ€Ğ¸ÑĞºĞ° â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def calculate_risk_metrics(self, df: pd.DataFrame, market_condition: str = "SIDEWAYS") -> RiskMetrics:
        """
        Ğ Ğ°ÑÑ‡Ñ‘Ñ‚ Ğ¼ĞµÑ‚Ñ€Ğ¸Ğº Ñ€Ğ¸ÑĞºĞ°:
        - volatility: std(pct_change) Ğ¿Ğ¾ lookback
        - atr_normalized: ATR/close
        - volume_ratio: vol / SMA(vol, lookback)
        - trend_strength: Ğ½Ğ¾Ñ€Ğ¼Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğ¹ Ğ½Ğ°ĞºĞ»Ğ¾Ğ½ EMA20
        """
        if df is None or df.empty or len(df) < max(self.volatility_lookback, 25):
            return self._default_risk_metrics(market_condition)

        self._stats["total_calculations"] += 1

        close = df["close"].astype("float64")
        returns = close.pct_change().dropna()
        if len(returns) >= self.volatility_lookback:
            volatility = float(returns.rolling(self.volatility_lookback).std().iloc[-1])
        else:
            volatility = float(returns.std())

        atr = self.get_unified_atr(df)
        last_price = float(close.iloc[-1]) if len(close) else 0.0
        atr_normalized = float(atr / last_price) if last_price > 0 else 0.0

        if "volume" in df.columns and len(df) >= self.volume_lookback:
            v_ma = df["volume"].rolling(self.volume_lookback).mean().iloc[-1]
            v_cur = df["volume"].iloc[-1]
            volume_ratio = float(v_cur / v_ma) if v_ma and v_ma > 0 else 1.0
        else:
            volume_ratio = 1.0

        trend_strength = _trend_strength_from_ema20(close)
        risk_level = self._determine_risk_level(volatility, atr_normalized)

        logger.debug(
            f"[RiskMetrics] vol={volatility:.4f}, atr_norm={atr_normalized:.4f}, "
            f"vr={volume_ratio:.2f}, trend={trend_strength:.3f}, level={risk_level.value}"
        )

        return RiskMetrics(
            volatility=volatility,
            atr_normalized=atr_normalized,
            volume_ratio=volume_ratio,
            trend_strength=trend_strength,
            market_condition=market_condition,
            risk_level=risk_level,
        )

    # â”€â”€ Ğ”Ğ¸Ğ½Ğ°Ğ¼Ğ¸Ñ‡ĞµÑĞºĞ¸Ğ¹ ÑÑ‚Ğ¾Ğ¿-Ğ»Ğ¾ÑÑ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def calculate_dynamic_stop_loss(
        self,
        entry_price: float,
        df: pd.DataFrame,
        market_condition: str = "SIDEWAYS",
    ) -> Tuple[float, Dict[str, Any]]:
        """Ğ¡Ñ‚Ñ€Ğ¾Ğ¸Ñ‚ SL Ğ¾Ñ‚ ATR Ñ ÑƒÑ‡Ñ‘Ñ‚Ğ¾Ğ¼ Ñ€ĞµĞ¶Ğ¸Ğ¼Ğ° Ñ€Ñ‹Ğ½ĞºĞ° Ğ¸ Ğ³Ñ€Ğ°Ğ½Ğ¸Ñ† Ğ¿Ñ€Ğ¾Ñ†ĞµĞ½Ñ‚Ğ¾Ğ². Ğ’Ğ¾Ğ·Ğ²Ñ€Ğ°Ñ‰Ğ°ĞµÑ‚ (sl_price, details)."""
        atr = self.get_unified_atr(df)
        risk = self.calculate_risk_metrics(df, market_condition)

        # Ğ±Ğ°Ğ·Ğ¾Ğ²Ñ‹Ğ¹ SL Ğ¾Ñ‚ ATR (1.5Ã—ATR Ğ½Ğ¸Ğ¶Ğµ Ğ²Ñ…Ğ¾Ğ´Ğ°)
        base_sl = entry_price - atr * 1.5

        # Ğ¼ÑƒĞ»ÑŒÑ‚Ğ¸Ğ¿Ğ»Ğ¸ĞºĞ°Ñ‚Ğ¾Ñ€Ñ‹
        mm = self.risk_multipliers.get(market_condition, {"stop": 1.0})
        vol_mult = 1.0 + (max(0.0, risk.volatility) * 5.0) * float(self.risk_multipliers.get(market_condition, {}).get("volatility", 1.0))
        stop_mult = float(mm.get("stop", 1.0))
        combined = vol_mult * stop_mult

        dyn_sl = entry_price - atr * 1.5 * combined

        # Ğ³Ñ€Ğ°Ğ½Ğ¸Ñ†Ñ‹
        min_stop = entry_price * (1.0 - self.min_stop_pct)
        max_stop = entry_price * (1.0 - self.max_stop_pct)
        final_sl = max(min_stop, min(dyn_sl, max_stop))

        details = {
            "entry_price": entry_price,
            "atr": atr,
            "base_sl": base_sl,
            "market_condition": market_condition,
            "volatility": risk.volatility,
            "risk_level": risk.risk_level.value,
            "vol_multiplier": vol_mult,
            "stop_multiplier": stop_mult,
            "combined_multiplier": combined,
            "dyn_sl": dyn_sl,
            "min_stop_boundary": min_stop,
            "max_stop_boundary": max_stop,
            "final_stop_pct": round((entry_price - final_sl) / entry_price * 100.0, 2),
        }

        logger.info(
            f"ğŸ›¡ï¸ Dynamic SL: {final_sl:.6f} "
            f"({details['final_stop_pct']:.2f}%), market={market_condition}, risk={risk.risk_level.value}"
        )
        return final_sl, details

    # â”€â”€ Ğ¡Ğ²Ğ¾Ğ´ĞºĞ¸/Ğ²Ğ°Ğ»Ğ¸Ğ´Ğ°Ñ†Ğ¸Ñ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def validate_configuration(self) -> List[str]:
        issues: List[str] = []
        if self.atr_period <= 0:
            issues.append(f"Invalid ATR period: {self.atr_period}")
        if self.atr_method not in ("ewm", "sma"):
            issues.append(f"Invalid ATR method: {self.atr_method}")
        if not (0 < self.min_stop_pct < self.max_stop_pct < 1):
            issues.append(f"Invalid stop loss boundaries: {self.min_stop_pct}..{self.max_stop_pct}")
        if self.volatility_lookback <= 0 or self.volume_lookback <= 0:
            issues.append("Invalid lookbacks")
        return issues

    def get_status_summary(self) -> Dict[str, Any]:
        return {
            "configuration_valid": len(self.validate_configuration()) == 0,
            "atr": {"period": self.atr_period, "method": self.atr_method},
            "stats": dict(self._stats),
            "stop_pct_bounds": {"min": self.min_stop_pct, "max": self.max_stop_pct},
            "risk_thresholds": {k.value: v for k, v in self.risk_thresholds.items()},
        }

    # â”€â”€ Ğ’ÑĞ¿Ğ¾Ğ¼Ğ¾Ğ³Ğ°Ñ‚ĞµĞ»ÑŒĞ½Ğ¾Ğµ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _determine_risk_level(self, volatility: float, atr_norm: float) -> RiskLevel:
        for level, th in self.risk_thresholds.items():
            if volatility <= th["vol"] and atr_norm <= th["atr"]:
                return level
        return RiskLevel.EXTREME

    def _default_risk_metrics(self, market_condition: str) -> RiskMetrics:
        return RiskMetrics(
            volatility=0.03,
            atr_normalized=0.02,
            volume_ratio=1.0,
            trend_strength=0.0,
            market_condition=market_condition,
            risk_level=RiskLevel.MEDIUM,
        )


# ĞĞ±Ñ€Ğ°Ñ‚Ğ½Ğ°Ñ ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ğ¾ÑÑ‚ÑŒ Ğ½Ğ° Ğ²ÑÑĞºĞ¸Ğ¹ ÑĞ»ÑƒÑ‡Ğ°Ğ¹
UnifiedRiskManager = RiskManager

__all__ = ["RiskManager", "UnifiedRiskManager", "RiskMetrics", "RiskLevel"]

