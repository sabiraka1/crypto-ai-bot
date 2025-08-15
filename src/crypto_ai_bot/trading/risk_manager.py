# -*- coding: utf-8 -*-
# src/crypto_ai_bot/trading/risk_manager.py
"""
🛡️ RiskManager — унифицированный риск-менеджер (без локальных дублей ATR/EMA)
Совместим с текущей архитектурой (Settings, Bot).

Особенности:
- ATR через crypto_ai_bot.core.indicators.unified.atr_last (никаких локальных реализаций)
- Пороговые настройки читаются из Settings (с дефолтами)
- Метрики риска: волатильность, нормированный ATR, объём, сила тренда
- Динамический стоп-лосс с учётом режима рынка и границ процентов
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

# ── Типы/структуры ──────────────────────────────────────────────────────────────
class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


@dataclass
class RiskMetrics:
    volatility: float          # std(pct_change) за окно
    atr_normalized: float      # ATR / close
    volume_ratio: float        # vol / SMA(vol, N)
    trend_strength: float      # нормированный наклон EMA20
    market_condition: str      # STRONG_BULL/WEAK_BULL/SIDEWAYS/WEAK_BEAR/STRONG_BEAR
    risk_level: RiskLevel


# ── Вспомогательные вычисления ─────────────────────────────────────────────────
def _trend_strength_from_ema20(close: pd.Series) -> float:
    """Нормированный наклон EMA20 за 5 последних точек ([-1..1])."""
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


# ── Класс RiskManager ──────────────────────────────────────────────────────────
class RiskManager:
    """
    Унифицированный риск-менеджер:
      - get_unified_atr(df)
      - calculate_risk_metrics(df, market_condition)
      - calculate_dynamic_stop_loss(entry_price, df, market_condition)
      - get_status_summary()
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.cfg = settings or Settings()  # допускаем вызов без DI
        # Базовые настройки (синхронизированы по духу с валидатором/entry)
        self.atr_period: int = int(getattr(self.cfg, "ATR_PERIOD", 14))
        self.atr_method: str = str(getattr(self.cfg, "RISK_ATR_METHOD", "ewm")).lower()
        self.atr_compare_enabled: bool = bool(getattr(self.cfg, "RISK_ATR_COMPARE", False))

        # Границы стопа (в долях цены): 0.5%..5% по умолчанию
        self.min_stop_pct: float = float(getattr(self.cfg, "MIN_STOP_PCT", 0.005))
        self.max_stop_pct: float = float(getattr(self.cfg, "MAX_STOP_PCT", 0.05))

        # Окна для метрик
        self.volatility_lookback: int = int(getattr(self.cfg, "VOLATILITY_LOOKBACK", 20))
        self.volume_lookback: int = int(getattr(self.cfg, "VOLUME_LOOKBACK", 20))

        # Карта мультипликаторов по «режиму рынка»
        self.risk_multipliers: Dict[str, Dict[str, float]] = {
            "STRONG_BULL": {"stop": 0.85, "volatility": 0.9},
            "WEAK_BULL":   {"stop": 1.00, "volatility": 1.0},
            "SIDEWAYS":    {"stop": 1.25, "volatility": 1.15},
            "WEAK_BEAR":   {"stop": 1.10, "volatility": 1.05},
            "STRONG_BEAR": {"stop": 0.95, "volatility": 1.00},
        }

        # Пороговые уровни риска (вола/ATR_norm)
        self.risk_thresholds: Dict[RiskLevel, Dict[str, float]] = {
            RiskLevel.LOW:     {"vol": 0.02, "atr": 0.015},
            RiskLevel.MEDIUM:  {"vol": 0.04, "atr": 0.030},
            RiskLevel.HIGH:    {"vol": 0.06, "atr": 0.045},
            RiskLevel.EXTREME: {"vol": float("inf"), "atr": float("inf")},
        }

        # Диагностика
        self._stats: Dict[str, Any] = {
            "total_calculations": 0,
            "unified_atr_calls": 0,
        }
        logger.info(f"🛡️ RiskManager ready (ATR period={self.atr_period}, method={self.atr_method})")

    # ── ATR ─────────────────────────────────────────────────────────────────────
    def get_unified_atr(self, df: pd.DataFrame, period: Optional[int] = None) -> float:
        """
        Унифицированный ATR (через core.indicators.unified.atr_last).
        Без локальных реализаций, чтобы не плодить дублирование.
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

    # ── Метрики риска ──────────────────────────────────────────────────────────
    def calculate_risk_metrics(self, df: pd.DataFrame, market_condition: str = "SIDEWAYS") -> RiskMetrics:
        """
        Расчёт метрик риска:
        - volatility: std(pct_change) по lookback
        - atr_normalized: ATR/close
        - volume_ratio: vol / SMA(vol, lookback)
        - trend_strength: нормированный наклон EMA20
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

    # ── Динамический стоп-лосс ─────────────────────────────────────────────────
    def calculate_dynamic_stop_loss(
        self,
        entry_price: float,
        df: pd.DataFrame,
        market_condition: str = "SIDEWAYS",
    ) -> Tuple[float, Dict[str, Any]]:
        """Строит SL от ATR с учётом режима рынка и границ процентов. Возвращает (sl_price, details)."""
        atr = self.get_unified_atr(df)
        risk = self.calculate_risk_metrics(df, market_condition)

        # базовый SL от ATR (1.5×ATR ниже входа)
        base_sl = entry_price - atr * 1.5

        # мультипликаторы
        mm = self.risk_multipliers.get(market_condition, {"stop": 1.0})
        vol_mult = 1.0 + (max(0.0, risk.volatility) * 5.0) * float(self.risk_multipliers.get(market_condition, {}).get("volatility", 1.0))
        stop_mult = float(mm.get("stop", 1.0))
        combined = vol_mult * stop_mult

        dyn_sl = entry_price - atr * 1.5 * combined

        # границы
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
            f"🛡️ Dynamic SL: {final_sl:.6f} "
            f"({details['final_stop_pct']:.2f}%), market={market_condition}, risk={risk.risk_level.value}"
        )
        return final_sl, details

    # ── Сводки/валидация ───────────────────────────────────────────────────────
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

    # ── Вспомогательное ────────────────────────────────────────────────────────
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


# Обратная совместимость на всякий случай
UnifiedRiskManager = RiskManager

__all__ = ["RiskManager", "UnifiedRiskManager", "RiskMetrics", "RiskLevel"]
