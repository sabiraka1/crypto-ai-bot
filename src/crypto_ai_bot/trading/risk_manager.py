# trading/risk_manager.py - UNIFIED ATR СИСТЕМА
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

class UnifiedRiskManager:
    """
    ✅ ПОЛНОСТЬЮ ПЕРЕПИСАННЫЙ: Unified Risk Manager с интеграцией ATR системы
    
    Особенности:
    - Использует ТОЛЬКО unified ATR функции
    - Поддержка config/settings.py параметров
    - Сравнение old vs new ATR для отладки
    - Адаптивные стоп-лоссы с рыночными модификаторами
    - Централизованное логирование с unified стилем
    """

    def __init__(self):
        # ✅ ПОЛУЧАЕМ КОНФИГУРАЦИЮ ИЗ SETTINGS
        try:
            from config.settings import TradingConfig
            self.config = TradingConfig()
            
            # ATR конфигурация
            atr_config = self.config.get_atr_config()
            self.atr_period = atr_config["period"]
            self.atr_method = atr_config["risk_method"]
            self.atr_compare_enabled = atr_config["compare_enabled"]
            
            # Риск конфигурация
            risk_config = self.config.get_risk_config()
            self.min_stop_pct = risk_config["min_stop_pct"]
            self.max_stop_pct = risk_config["max_stop_pct"]
            self.volatility_lookback = risk_config["volatility_lookback"]
            self.volume_lookback = risk_config["volume_lookback"]
            self.market_modifiers = risk_config["market_modifiers"]
            
            logging.info(f"🛡️ UnifiedRiskManager: ATR period={self.atr_period}, method={self.atr_method}")
            
        except Exception as e:
            logging.error(f"Failed to load config, using defaults: {e}")
            # Fallback к дефолтным значениям
            self._load_defaults()

        # Мультипликаторы риска по рыночным условиям
        self.risk_multipliers = {
            "STRONG_BULL": {"stop": 0.8, "volatility": 0.9},
            "WEAK_BULL": {"stop": 1.0, "volatility": 1.0},
            "SIDEWAYS": {"stop": 1.3, "volatility": 1.2},
            "WEAK_BEAR": {"stop": 1.1, "volatility": 1.1},
            "STRONG_BEAR": {"stop": 0.9, "volatility": 1.0}
        }

        # Границы риска для классификации
        self.risk_thresholds = {
            RiskLevel.LOW: {"vol": 0.02, "atr": 0.015},
            RiskLevel.MEDIUM: {"vol": 0.04, "atr": 0.03},
            RiskLevel.HIGH: {"vol": 0.06, "atr": 0.045},
            RiskLevel.EXTREME: {"vol": float("inf"), "atr": float("inf")}
        }

        # Статистика для отладки
        self._stats = {
            "total_calculations": 0,
            "unified_atr_calls": 0,
            "fallback_calls": 0,
            "comparison_warnings": 0
        }

    def _load_defaults(self):
        """Загрузка дефолтных значений при ошибке конфигурации"""
        self.atr_period = int(os.getenv("ATR_PERIOD", 14))
        self.atr_method = os.getenv("RISK_ATR_METHOD", "ewm").lower()
        self.atr_compare_enabled = os.getenv("RISK_ATR_COMPARE", "1") == "1"
        self.min_stop_pct = float(os.getenv("MIN_STOP_PCT", 0.005))
        self.max_stop_pct = float(os.getenv("MAX_STOP_PCT", 0.05))
        self.volatility_lookback = int(os.getenv("VOLATILITY_LOOKBACK", 20))
        self.volume_lookback = int(os.getenv("VOLUME_LOOKBACK", 20))
        self.market_modifiers = {
            "bull": float(os.getenv("BULL_MARKET_MODIFIER", -0.20)),
            "bear": float(os.getenv("BEAR_MARKET_MODIFIER", 0.40)),
            "overheated": float(os.getenv("OVERHEATED_MODIFIER", 0.30))
        }

    # =========================================================================
    # ✅ UNIFIED ATR INTEGRATION
    # =========================================================================

    def get_unified_atr(self, df: pd.DataFrame, period: Optional[int] = None) -> float:
        """
        ✅ ГЛАВНАЯ ФУНКЦИЯ: Получение ATR через unified систему
        
        Args:
            df: DataFrame с OHLCV данными
            period: Период ATR (если None - использует self.atr_period)
            
        Returns:
            float: ATR значение
        """
        try:
            from analysis.technical_indicators import _atr_for_risk_manager
            
            # Используем период из конфигурации если не задан
            atr_period = period if period is not None else self.atr_period
            
            # ✅ UNIFIED ATR CALL
            unified_atr = _atr_for_risk_manager(df, atr_period)
            self._stats["unified_atr_calls"] += 1
            
            # ✅ ОПЦИОНАЛЬНОЕ СРАВНЕНИЕ С LEGACY (для отладки)
            if self.atr_compare_enabled:
                self._compare_with_legacy_atr(df, unified_atr, atr_period)
            
            logging.debug(f"🛡️ Risk Manager ATR (UNIFIED): {unified_atr:.6f} | period={atr_period} | method={self.atr_method}")
            return unified_atr
            
        except Exception as e:
            logging.error(f"🛡️ Unified ATR failed in risk manager: {e}")
            self._stats["fallback_calls"] += 1
            return self._fallback_atr(df, period or self.atr_period)

    def _compare_with_legacy_atr(self, df: pd.DataFrame, unified_atr: float, period: int):
        """Сравнение unified ATR с legacy методом для отладки"""
        try:
            # Legacy ATR расчет
            if df is None or df.empty or len(df) < period:
                return
                
            high = df["high"].astype("float64")
            low = df["low"].astype("float64") 
            close = df["close"].astype("float64")
            
            prev_close = close.shift(1)
            tr1 = (high - low).abs()
            tr2 = (high - prev_close).abs()
            tr3 = (low - prev_close).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            
            if self.atr_method == "sma":
                legacy_atr = tr.rolling(window=period, min_periods=1).mean().iloc[-1]
            else:
                legacy_atr = tr.ewm(alpha=1/period, adjust=False, min_periods=1).mean().iloc[-1]
            
            # Сравнение
            difference = abs(unified_atr - legacy_atr)
            difference_pct = (difference / max(unified_atr, legacy_atr)) * 100
            
            if difference_pct > 1.0:  # Больше 1% расхождения
                self._stats["comparison_warnings"] += 1
                logging.warning(f"🛡️ ATR COMPARISON: unified={unified_atr:.6f}, legacy={legacy_atr:.6f}, diff={difference_pct:.2f}%")
            else:
                logging.debug(f"🛡️ ATR COMPARISON OK: diff={difference_pct:.2f}%")
                
        except Exception as e:
            logging.debug(f"ATR comparison failed: {e}")

    def _fallback_atr(self, df: pd.DataFrame, period: int) -> float:
        """Критический fallback для ATR расчета"""
        try:
            if df is None or df.empty:
                return 100.0  # Экстремальный fallback
                
            # Простейший ATR расчет
            price_range = (df["high"] - df["low"]).mean()
            return float(price_range) if pd.notna(price_range) and price_range > 0 else 100.0
            
        except Exception:
            return 100.0

    # =========================================================================
    # RISK METRICS CALCULATION
    # =========================================================================

    def calculate_risk_metrics(self, df: pd.DataFrame, market_condition: str = "SIDEWAYS") -> RiskMetrics:
        """✅ ОБНОВЛЕНО: Расчет метрик риска с unified ATR"""
        if df is None or df.empty or len(df) < self.volatility_lookback:
            return self._default_risk_metrics()

        try:
            self._stats["total_calculations"] += 1
            
            # Волатильность доходностей
            returns = df["close"].pct_change().dropna()
            if len(returns) >= self.volatility_lookback:
                volatility = returns.rolling(self.volatility_lookback).std().iloc[-1]
            else:
                volatility = returns.std()
            volatility = float(volatility) if pd.notna(volatility) else 0.03

            # ✅ UNIFIED ATR
            atr = self.get_unified_atr(df)
            atr_normalized = atr / df["close"].iloc[-1] if df["close"].iloc[-1] > 0 else 0.02

            # Объемный анализ
            if "volume" in df.columns and len(df) >= self.volume_lookback:
                volume_ma = df["volume"].rolling(self.volume_lookback).mean()
                current_volume = df["volume"].iloc[-1]
                volume_ratio = current_volume / volume_ma.iloc[-1] if volume_ma.iloc[-1] > 0 else 1.0
            else:
                volume_ratio = 1.0

            # Сила тренда
            ema_20 = df["close"].ewm(span=20).mean()
            trend_strength = self._calculate_trend_strength(ema_20)

            # Определение уровня риска
            risk_level = self._determine_risk_level(volatility, atr_normalized)

            metrics = RiskMetrics(
                volatility=float(volatility),
                atr_normalized=float(atr_normalized),
                volume_ratio=float(volume_ratio),
                trend_strength=float(trend_strength),
                market_condition=market_condition,
                risk_level=risk_level
            )

            logging.debug(f"🛡️ Risk metrics: vol={volatility:.4f}, atr_norm={atr_normalized:.4f}, level={risk_level.value}")
            return metrics

        except Exception as e:
            logging.error(f"🛡️ Risk metrics calculation failed: {e}")
            return self._default_risk_metrics()

    def calculate_dynamic_stop_loss(self, entry_price: float, df: pd.DataFrame, 
                                  market_condition: str = "SIDEWAYS") -> Tuple[float, Dict[str, Any]]:
        """✅ ОБНОВЛЕНО: Динамический стоп-лосс с unified ATR"""
        try:
            risk_metrics = self.calculate_risk_metrics(df, market_condition)
            
            # ✅ UNIFIED ATR для стоп-лосса
            atr = self.get_unified_atr(df)
            
            # Базовый ATR стоп (1.5x ATR ниже входа)
            base_atr_stop = entry_price - (atr * 1.5)

            # Мультипликаторы на основе рыночных условий
            volatility_multiplier = 1 + (risk_metrics.volatility * 5)
            market_multiplier = self.risk_multipliers.get(market_condition, {"stop": 1.0})["stop"]
            volume_multiplier = 1 / (1 + max(0, risk_metrics.volume_ratio - 1) * 0.3)

            # Комбинированный мультипликатор
            combined_multiplier = volatility_multiplier * market_multiplier * volume_multiplier
            
            # Динамический стоп
            dynamic_stop = entry_price - (atr * 1.5 * combined_multiplier)

            # Применение границ
            min_stop = entry_price * (1 - self.min_stop_pct)
            max_stop = entry_price * (1 - self.max_stop_pct)
            final_stop = max(min_stop, min(dynamic_stop, max_stop))

            # Детали для логирования
            details = {
                "entry_price": entry_price,
                "base_atr_stop": base_atr_stop,
                "atr_value": atr,
                "atr_method": self.atr_method,
                "volatility": risk_metrics.volatility,
                "volatility_multiplier": volatility_multiplier,
                "market_condition": market_condition,
                "market_multiplier": market_multiplier,
                "volume_multiplier": volume_multiplier,
                "combined_multiplier": combined_multiplier,
                "dynamic_stop": dynamic_stop,
                "risk_level": risk_metrics.risk_level.value,
                "final_stop_pct": round((entry_price - final_stop) / entry_price * 100, 2),
                "min_stop_boundary": min_stop,
                "max_stop_boundary": max_stop
            }

            logging.info(f"🛡️ Dynamic SL: {final_stop:.6f} ({details['final_stop_pct']:.2f}%) | "
                        f"Risk: {risk_metrics.risk_level.value} | Market: {market_condition}")
            
            return final_stop, details

        except Exception as e:
            logging.error(f"🛡️ Dynamic stop loss calculation failed: {e}")
            # Fallback к простому процентному стопу
            fallback_stop = entry_price * (1 - 0.02)  # 2%
            return fallback_stop, {
                "error": str(e),
                "fallback_stop": fallback_stop,
                "fallback_pct": 2.0
            }

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def _calculate_trend_strength(self, ema_series: pd.Series) -> float:
        """Расчет силы тренда через регрессию"""
        if len(ema_series) < 5:
            return 0.0
            
        try:
            x = np.arange(5)
            y = ema_series.iloc[-5:].values
            if len(y) < 5 or not np.all(np.isfinite(y)):
                return 0.0
            slope = np.polyfit(x, y, 1)[0]
            return float(np.clip((slope / y[-1]) * 1000, -1, 1))
        except Exception:
            return 0.0

    def _determine_risk_level(self, volatility: float, atr_normalized: float) -> RiskLevel:
        """Определение уровня риска по метрикам"""
        for level, thresholds in self.risk_thresholds.items():
            if volatility <= thresholds["vol"] and atr_normalized <= thresholds["atr"]:
                return level
        return RiskLevel.EXTREME

    def _default_risk_metrics(self) -> RiskMetrics:
        """Дефолтные метрики при ошибках"""
        return RiskMetrics(
            volatility=0.03,
            atr_normalized=0.02,
            volume_ratio=1.0,
            trend_strength=0.0,
            market_condition="SIDEWAYS",
            risk_level=RiskLevel.MEDIUM
        )

    # =========================================================================
    # DIAGNOSTICS & MONITORING
    # =========================================================================

    def get_atr_diagnostics(self) -> Dict[str, Any]:
        """✅ НОВОЕ: Диагностика unified ATR системы"""
        return {
            "config": {
                "atr_period": self.atr_period,
                "atr_method": self.atr_method,
                "compare_enabled": self.atr_compare_enabled,
                "min_stop_pct": self.min_stop_pct,
                "max_stop_pct": self.max_stop_pct
            },
            "stats": dict(self._stats),
            "thresholds": {level.value: thresholds for level, thresholds in self.risk_thresholds.items()},
            "market_modifiers": self.risk_multipliers
        }

    def reset_stats(self):
        """Сброс статистики"""
        self._stats = {
            "total_calculations": 0,
            "unified_atr_calls": 0,
            "fallback_calls": 0,
            "comparison_warnings": 0
        }
        logging.info("🛡️ Risk manager stats reset")

    def set_atr_method(self, method: str):
        """Изменение метода ATR расчета"""
        if method.lower() in ["ewm", "sma"]:
            self.atr_method = method.lower()
            logging.info(f"🛡️ ATR method changed to: {self.atr_method}")
        else:
            logging.error(f"🛡️ Invalid ATR method: {method}")

    def enable_atr_comparison(self, enabled: bool):
        """Включение/отключение сравнения ATR"""
        self.atr_compare_enabled = enabled
        logging.info(f"🛡️ ATR comparison {'enabled' if enabled else 'disabled'}")

    def validate_configuration(self) -> List[str]:
        """Валидация конфигурации риск-менеджера"""
        issues = []
        
        if self.atr_period <= 0:
            issues.append(f"Invalid ATR period: {self.atr_period}")
            
        if self.atr_method not in ["ewm", "sma"]:
            issues.append(f"Invalid ATR method: {self.atr_method}")
            
        if not (0 < self.min_stop_pct < self.max_stop_pct < 1):
            issues.append(f"Invalid stop loss boundaries: {self.min_stop_pct} - {self.max_stop_pct}")
            
        if self.volatility_lookback <= 0:
            issues.append(f"Invalid volatility lookback: {self.volatility_lookback}")
            
        return issues

    def get_status_summary(self) -> Dict[str, Any]:
        """Сводка состояния риск-менеджера"""
        validation_issues = self.validate_configuration()
        
        return {
            "configuration_valid": len(validation_issues) == 0,
            "validation_issues": validation_issues,
            "atr_config": {
                "period": self.atr_period,
                "method": self.atr_method,
                "compare_enabled": self.atr_compare_enabled
            },
            "performance": self._stats,
            "unified_atr_health": "OK" if self._stats["fallback_calls"] < self._stats["unified_atr_calls"] * 0.1 else "WARNING"
        }

# =========================================================================
# ✅ ОБРАТНАЯ СОВМЕСТИМОСТЬ
# =========================================================================

# Алиас для старого кода
RiskManager = UnifiedRiskManager
AdaptiveRiskManager = UnifiedRiskManager

# Для импорта в других модулях
__all__ = [
    'UnifiedRiskManager', 
    'RiskManager',  # Алиас
    'AdaptiveRiskManager',  # Алиас
    'RiskLevel', 
    'RiskMetrics'
]