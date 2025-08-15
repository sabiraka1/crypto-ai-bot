# src/crypto_ai_bot/trading/risk_manager.py
"""
рџ›ЎпёЏ RiskManager вЂ” Р»С‘РіРєРёР№ СѓРЅРёС„РёС†РёСЂРѕРІР°РЅРЅС‹Р№ СЂРёСЃРє-РјРµРЅРµРґР¶РµСЂ
РЎРѕРІРјРµСЃС‚РёРј СЃ С‚РµРєСѓС‰РµР№ Р°СЂС…РёС‚РµРєС‚СѓСЂРѕР№ (Settings, Bot, PositionManager).

РћСЃРѕР±РµРЅРЅРѕСЃС‚Рё:
- ATR С‡РµСЂРµР· crypto_ai_bot.analysis.get_unified_atr (СЃ Wilder-fallback)
- РџРѕСЂРѕРіРѕРІС‹Рµ РЅР°СЃС‚СЂРѕР№РєРё С‡РёС‚Р°СЋС‚СЃСЏ РёР· Settings (СЃ РґРµС„РѕР»С‚Р°РјРё)
- РњРµС‚СЂРёРєРё СЂРёСЃРєР°: РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ, РЅРѕСЂРјРёСЂРѕРІР°РЅРЅС‹Р№ ATR, РѕР±СЉС‘Рј, СЃРёР»Р° С‚СЂРµРЅРґР°
- Р”РёРЅР°РјРёС‡РµСЃРєРёР№ СЃС‚РѕРї-Р»РѕСЃСЃ СЃ СѓС‡С‘С‚РѕРј СЂРµР¶РёРјР° СЂС‹РЅРєР° Рё РіСЂР°РЅРёС† РїСЂРѕС†РµРЅС‚РѕРІ
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, Tuple, List

import numpy as np
import pandas as pd

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.indicators.unified import get_unified_atr as _get_unified_atr

logger = logging.getLogger(__name__)


# в”Ђв”Ђ РўРёРїС‹/СЃС‚СЂСѓРєС‚СѓСЂС‹ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


@dataclass
class RiskMetrics:
    volatility: float          # std(pct_change) Р·Р° РѕРєРЅРѕ
    atr_normalized: float      # ATR / close
    volume_ratio: float        # vol / SMA(vol, N)
    trend_strength: float      # РЅР°РєР»РѕРЅ EMA20 (РЅРѕСЂРјРёСЂРѕРІР°РЅРЅС‹Р№)
    market_condition: str      # STRONG_BULL/WEAK_BULL/SIDEWAYS/WEAK_BEAR/STRONG_BEAR
    risk_level: RiskLevel


# в”Ђв”Ђ Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅС‹Рµ РІС‹С‡РёСЃР»РµРЅРёСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def _wilder_atr(df: pd.DataFrame, period: int = 14) -> float:
    """True ATR (Wilder): TR=max(H-L, |H-Cprev|, |L-Cprev|), EMA(alpha=1/period)."""
    if df is None or df.empty or len(df) < 2:
        return float("nan")
    h, l, c = df["high"].astype("float64"), df["low"].astype("float64"), df["close"].astype("float64")
    c_prev = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    val = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else float("nan")
    return val


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _trend_strength_from_ema20(close: pd.Series) -> float:
    """РќРѕСЂРјРёСЂРѕРІР°РЅРЅС‹Р№ РЅР°РєР»РѕРЅ EMA20 Р·Р° 5 РїРѕСЃР»РµРґРЅРёС… С‚РѕС‡РµРє ([-1..1])."""
    if close is None or len(close) < 25:
        return 0.0
    ema20 = _ema(close, 20)
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


# в”Ђв”Ђ РљР»Р°СЃСЃ RiskManager в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
class RiskManager:
    """
    РЈРЅРёС„РёС†РёСЂРѕРІР°РЅРЅС‹Р№ СЂРёСЃРє-РјРµРЅРµРґР¶РµСЂ:
      - get_unified_atr(df)
      - calculate_risk_metrics(df, market_condition)
      - calculate_dynamic_stop_loss(entry_price, df, market_condition)
      - get_status_summary()
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.cfg = settings or Settings()  # РґРѕРїСѓСЃРєР°РµРј РІС‹Р·РѕРІ Р±РµР· DI
        # Р‘Р°Р·РѕРІС‹Рµ РЅР°СЃС‚СЂРѕР№РєРё (СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅС‹ РїРѕ РґСѓС…Сѓ СЃ РІР°Р»РёРґР°С‚РѕСЂРѕРј/entry)
        self.atr_period: int = int(getattr(self.cfg, "ATR_PERIOD", 14))
        self.atr_method: str = str(getattr(self.cfg, "RISK_ATR_METHOD", "ewm")).lower()
        self.atr_compare_enabled: bool = bool(getattr(self.cfg, "RISK_ATR_COMPARE", False))

        # Р“СЂР°РЅРёС†С‹ СЃС‚РѕРїР° (РІ РґРѕР»СЏС… С†РµРЅС‹): 0.5%..5% РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ
        self.min_stop_pct: float = float(getattr(self.cfg, "MIN_STOP_PCT", 0.005))
        self.max_stop_pct: float = float(getattr(self.cfg, "MAX_STOP_PCT", 0.05))

        # РћРєРЅР° РґР»СЏ РјРµС‚СЂРёРє
        self.volatility_lookback: int = int(getattr(self.cfg, "VOLATILITY_LOOKBACK", 20))
        self.volume_lookback: int = int(getattr(self.cfg, "VOLUME_LOOKBACK", 20))

        # РљР°СЂС‚Р° РјСѓР»СЊС‚РёРїР»РёРєР°С‚РѕСЂРѕРІ РїРѕ В«СЂРµР¶РёРјСѓ СЂС‹РЅРєР°В»
        self.risk_multipliers: Dict[str, Dict[str, float]] = {
            "STRONG_BULL": {"stop": 0.85, "volatility": 0.9},
            "WEAK_BULL":   {"stop": 1.00, "volatility": 1.0},
            "SIDEWAYS":    {"stop": 1.25, "volatility": 1.15},
            "WEAK_BEAR":   {"stop": 1.10, "volatility": 1.05},
            "STRONG_BEAR": {"stop": 0.95, "volatility": 1.00},
        }

        # РџРѕСЂРѕРіРѕРІС‹Рµ СѓСЂРѕРІРЅРё СЂРёСЃРєР° (РІРѕР»Р°/ATR_norm)
        self.risk_thresholds: Dict[RiskLevel, Dict[str, float]] = {
            RiskLevel.LOW:     {"vol": 0.02, "atr": 0.015},
            RiskLevel.MEDIUM:  {"vol": 0.04, "atr": 0.030},
            RiskLevel.HIGH:    {"vol": 0.06, "atr": 0.045},
            RiskLevel.EXTREME: {"vol": float("inf"), "atr": float("inf")},
        }

        # Р”РёР°РіРЅРѕСЃС‚РёРєР°
        self._stats: Dict[str, Any] = {
            "total_calculations": 0,
            "unified_atr_calls": 0,
            "fallback_calls": 0,
        }
        logger.info(f"рџ›ЎпёЏ RiskManager ready (ATR period={self.atr_period}, method={self.atr_method})")

    # в”Ђв”Ђ ATR в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def get_unified_atr(self, df: pd.DataFrame, period: Optional[int] = None) -> float:
        """
        РЈРЅРёС„РёС†РёСЂРѕРІР°РЅРЅС‹Р№ ATR РёР· РѕР±С‰РµРіРѕ РјРѕРґСѓР»СЏ; РµСЃР»Рё РЅРµ СѓРґР°С‘С‚СЃСЏ вЂ” Wilder fallback.
        """
        p = int(period or self.atr_period)
        try:
            val = _get_unified_atr(df, p, method=self.atr_method)
            self._stats["unified_atr_calls"] += 1
            return float(val)
        except Exception as e:
            logger.warning(f"ATR fallback (Wilder) due to: {e}")
            self._stats["fallback_calls"] += 1
            return float(_wilder_atr(df, p))

    # в”Ђв”Ђ РњРµС‚СЂРёРєРё СЂРёСЃРєР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def calculate_risk_metrics(self, df: pd.DataFrame, market_condition: str = "SIDEWAYS") -> RiskMetrics:
        """
        Р Р°СЃС‡С‘С‚ РјРµС‚СЂРёРє СЂРёСЃРєР°:
        - volatility: std(pct_change) РїРѕ lookback
        - atr_normalized: ATR/close
        - volume_ratio: vol / SMA(vol, lookback)
        - trend_strength: РЅРѕСЂРјРёСЂРѕРІР°РЅРЅС‹Р№ РЅР°РєР»РѕРЅ EMA20
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

    # в”Ђв”Ђ Р”РёРЅР°РјРёС‡РµСЃРєРёР№ СЃС‚РѕРї-Р»РѕСЃСЃ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def calculate_dynamic_stop_loss(
        self,
        entry_price: float,
        df: pd.DataFrame,
        market_condition: str = "SIDEWAYS",
    ) -> Tuple[float, Dict[str, Any]]:
        """
        РЎС‚СЂРѕРёС‚ SL РѕС‚ ATR СЃ СѓС‡С‘С‚РѕРј СЂРµР¶РёРјР° СЂС‹РЅРєР° Рё РіСЂР°РЅРёС† РїСЂРѕС†РµРЅС‚РѕРІ.
        Р’РѕР·РІСЂР°С‰Р°РµС‚ (sl_price, details).
        """
        atr = self.get_unified_atr(df)
        risk = self.calculate_risk_metrics(df, market_condition)

        # Р±Р°Р·РѕРІС‹Р№ SL РѕС‚ ATR (1.5Г—ATR РЅРёР¶Рµ РІС…РѕРґР°)
        base_sl = entry_price - atr * 1.5

        # РјСѓР»СЊС‚РёРїР»РёРєР°С‚РѕСЂС‹
        mm = self.risk_multipliers.get(market_condition, {"stop": 1.0})
        vol_mult = 1.0 + (max(0.0, risk.volatility) * 5.0) * float(self.risk_multipliers.get(market_condition, {}).get("volatility", 1.0))
        stop_mult = float(mm.get("stop", 1.0))
        combined = vol_mult * stop_mult

        dyn_sl = entry_price - atr * 1.5 * combined

        # РіСЂР°РЅРёС†С‹
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
            f"рџ›ЎпёЏ Dynamic SL: {final_sl:.6f} "
            f"({details['final_stop_pct']:.2f}%), market={market_condition}, risk={risk.risk_level.value}"
        )
        return final_sl, details

    # в”Ђв”Ђ РЎРІРѕРґРєРё/РІР°Р»РёРґР°С†РёСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
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

    # в”Ђв”Ђ Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅРѕРµ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
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


# РћР±СЂР°С‚РЅР°СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ РЅР° РІСЃСЏРєРёР№ СЃР»СѓС‡Р°Р№
UnifiedRiskManager = RiskManager

__all__ = ["RiskManager", "UnifiedRiskManager", "RiskMetrics", "RiskLevel"]







