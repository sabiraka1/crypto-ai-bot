# analysis/market_analyzer.py

import logging
from typing import Tuple

import numpy as np
import pandas as pd

from config.settings import MarketCondition

_EPS = 1e-12


class MultiTimeframeAnalyzer:
    """вњ… РРЎРџР РђР’Р›Р•РќРћ: РђРЅР°Р»РёР· СЂС‹РЅРєР° РЅР° РґРІСѓС… РўР¤ (1D Рё 4H) СЃ unified ATR СЃРёСЃС‚РµРјРѕР№."""

    def __init__(self):
        # РІРµСЃР° РўР¤
        self._w_daily = 0.6
        self._w_h4 = 0.4
        # РїР°СЂР°РјРµС‚СЂС‹
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

            logging.info(f"рџ“Љ Market Analysis: {condition.value}, Confidence: {confidence:.2f}")
            return condition, confidence
        except Exception as e:
            logging.exception(f"Market analysis failed: {e}")
            return MarketCondition.SIDEWAYS, 0.10

    # ---------- internals ----------
    def _trend(self, df: pd.DataFrame) -> float:
        """РќР°РїСЂР°РІР»РµРЅРёРµ С‚СЂРµРЅРґР° РІ [-1..1]. РЈСЃС‚РѕР№С‡РёРІРѕ Рє РєРѕСЂРѕС‚РєРёРј СЃРµСЂРёСЏРј."""
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
        """вњ… РРЎРџР РђР’Р›Р•РќРћ: РЎРёР»Р° С‚СЂРµРЅРґР° СЃ unified ATR (СѓР±СЂР°РЅРѕ РґСѓР±Р»РёСЂРѕРІР°РЅРёРµ)."""
        if df is None or df.empty or "close" not in df or "high" not in df or "low" not in df:
            return 0.5

        close = df["close"].astype("float64")
        high = df["high"].astype("float64")
        low = df["low"].astype("float64")

        # РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ РґРѕС…РѕРґРЅРѕСЃС‚РµР№
        ret = close.pct_change().dropna()
        vol = float(ret.rolling(window=min(self._vol_window, max(5, len(ret)))).std().iloc[-1]) if len(ret) >= 5 else float(ret.std() or 0.0)
        vol = max(0.0, vol)

        # вњ… РРЎРџР РђР’Р›Р•РќРћ: СѓР±СЂР°РЅРѕ РґСѓР±Р»РёСЂРѕРІР°РЅРёРµ ATR РІС‹Р·РѕРІР°
        try:
            from crypto_ai_bot.core.indicators.unified import _atr_series_for_ml
            temp_df = pd.DataFrame({'high': high, 'low': low, 'close': close})
            atr = _atr_series_for_ml(temp_df, self._atr_period)
            atr_norm = float((atr.iloc[-1] / (abs(close.iloc[-1]) + _EPS)) if atr.notna().any() else 0.0)
            logging.debug(f"рџ“Љ Market Analyzer: Using UNIFIED ATR for strength calculation: {atr.iloc[-1]:.6f}")
        except Exception as e:
            logging.warning(f"рџ“Љ Market Analyzer: UNIFIED ATR failed, using fallback: {e}")
            # Fallback Рє РїСЂРѕСЃС‚РѕРјСѓ СЂР°СЃС‡РµС‚Сѓ
            atr_simple = (high - low).mean()
            atr_norm = float(atr_simple / (abs(close.iloc[-1]) + _EPS)) if pd.notna(atr_simple) else 0.02

        # СЃРіР»Р°Р¶С‘РЅРЅР°СЏ РјРµС‚СЂРёРєР° СЃРёР»С‹: РЅРёР¶Рµ vol/atr_norm -> РІС‹С€Рµ СЃРёР»Р°
        # РїР°СЂР°РјРµС‚СЂС‹ РїРѕРґРѕР±СЂР°РЅС‹, С‡С‚РѕР±С‹ РґРёР°РїР°Р·РѕРЅ Р±С‹Р» ~[0.2..0.9] РґР»СЏ СЂРµР°Р»СЊРЅС‹С… СЂС‹РЅРєРѕРІ
        strength = 1.0 / (1.0 + 120.0 * vol + 15.0 * atr_norm)
        
        logging.debug(f"рџ“Љ Market strength calculation: vol={vol:.4f}, atr_norm={atr_norm:.4f}, strength={strength:.3f}")
        
        return float(np.clip(strength, 0.0, 1.0))

    def _classify(self, trend: float, strength: float) -> MarketCondition:
        """РљР»Р°СЃСЃРёС„РёРєР°С†РёСЏ СЂС‹РЅРѕС‡РЅРѕРіРѕ СЃРѕСЃС‚РѕСЏРЅРёСЏ"""
        if trend > 0.10 and strength > 0.70:
            return MarketCondition.STRONG_BULL
        if trend > 0.05 and strength > 0.50:
            return MarketCondition.WEAK_BULL
        if trend < -0.10 and strength > 0.70:
            return MarketCondition.STRONG_BEAR
        if trend < -0.05 and strength > 0.50:
            return MarketCondition.WEAK_BEAR
        return MarketCondition.SIDEWAYS

    # =========================================================================
    # вњ… РќРћР’Р«Р• Р”РРђР“РќРћРЎРўРР§Р•РЎРљРР• РњР•РўРћР”Р«
    # =========================================================================

    def get_diagnostics(self, df_1d: pd.DataFrame, df_4h: pd.DataFrame) -> dict:
        """вњ… РќРћР’РћР•: Р”РёР°РіРЅРѕСЃС‚РёРєР° Р°РЅР°Р»РёР·Р° СЂС‹РЅРєР°"""
        try:
            # РўСЂРµРЅРґС‹ РїРѕ С‚Р°Р№РјС„СЂРµР№РјР°Рј
            trend_1d = self._trend(df_1d)
            trend_4h = self._trend(df_4h)
            
            # РЎРёР»С‹ РїРѕ С‚Р°Р№РјС„СЂРµР№РјР°Рј
            strength_1d = self._strength(df_1d)
            strength_4h = self._strength(df_4h)
            
            # РљРѕРјР±РёРЅРёСЂРѕРІР°РЅРЅС‹Рµ Р·РЅР°С‡РµРЅРёСЏ
            combined_trend = float(self._w_daily * trend_1d + self._w_h4 * trend_4h)
            combined_strength = float(self._w_daily * strength_1d + self._w_h4 * strength_4h)
            
            # Р¤РёРЅР°Р»СЊРЅР°СЏ РєР»Р°СЃСЃРёС„РёРєР°С†РёСЏ
            condition = self._classify(combined_trend, combined_strength)
            confidence = float(np.clip(abs(combined_trend) * combined_strength, 0.0, 1.0))
            
            return {
                "timeframes": {
                    "1d": {"trend": trend_1d, "strength": strength_1d},
                    "4h": {"trend": trend_4h, "strength": strength_4h}
                },
                "combined": {
                    "trend": combined_trend,
                    "strength": combined_strength,
                    "condition": condition.value,
                    "confidence": confidence
                },
                "weights": {
                    "daily": self._w_daily,
                    "4h": self._w_h4
                },
                "parameters": {
                    "ema_fast": self._ema_fast,
                    "ema_slow": self._ema_slow,
                    "atr_period": self._atr_period,
                    "momentum_lookback": self._momentum_lookback,
                    "vol_window": self._vol_window
                }
            }
            
        except Exception as e:
            logging.error(f"рџ“Љ Market analyzer diagnostics failed: {e}")
            return {"error": str(e)}

    def validate_data_quality(self, df_1d: pd.DataFrame, df_4h: pd.DataFrame) -> dict:
        """вњ… РќРћР’РћР•: Р’Р°Р»РёРґР°С†РёСЏ РєР°С‡РµСЃС‚РІР° РґР°РЅРЅС‹С…"""
        issues = []
        warnings = []
        
        # РџСЂРѕРІРµСЂРєР° 1D РґР°РЅРЅС‹С…
        if df_1d is None or df_1d.empty:
            issues.append("1D DataFrame is empty or None")
        else:
            required_cols = {"open", "high", "low", "close", "volume"}
            missing_1d = required_cols - set(df_1d.columns)
            if missing_1d:
                issues.append(f"1D data missing columns: {missing_1d}")
            
            if len(df_1d) < self._momentum_lookback:
                warnings.append(f"1D data has only {len(df_1d)} rows, need >= {self._momentum_lookback}")
            
            # РџСЂРѕРІРµСЂРєР° РЅР° NaN
            if df_1d.isnull().any().any():
                warnings.append("1D data contains NaN values")
        
        # РџСЂРѕРІРµСЂРєР° 4H РґР°РЅРЅС‹С…
        if df_4h is None or df_4h.empty:
            issues.append("4H DataFrame is empty or None")
        else:
            required_cols = {"open", "high", "low", "close", "volume"}
            missing_4h = required_cols - set(df_4h.columns)
            if missing_4h:
                issues.append(f"4H data missing columns: {missing_4h}")
            
            if len(df_4h) < self._momentum_lookback:
                warnings.append(f"4H data has only {len(df_4h)} rows, need >= {self._momentum_lookback}")
                
            # РџСЂРѕРІРµСЂРєР° РЅР° NaN
            if df_4h.isnull().any().any():
                warnings.append("4H data contains NaN values")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "data_quality": {
                "1d_rows": len(df_1d) if df_1d is not None else 0,
                "4h_rows": len(df_4h) if df_4h is not None else 0,
                "min_required_rows": self._momentum_lookback
            }
        }

    def get_configuration(self) -> dict:
        """вњ… РќРћР’РћР•: РџРѕР»СѓС‡РµРЅРёРµ С‚РµРєСѓС‰РµР№ РєРѕРЅС„РёРіСѓСЂР°С†РёРё Р°РЅР°Р»РёР·Р°С‚РѕСЂР°"""
        return {
            "timeframe_weights": {
                "daily": self._w_daily,
                "4h": self._w_h4
            },
            "ema_parameters": {
                "fast": self._ema_fast,
                "slow": self._ema_slow
            },
            "analysis_parameters": {
                "atr_period": self._atr_period,
                "momentum_lookback": self._momentum_lookback,
                "volatility_window": self._vol_window
            },
            "classification_thresholds": {
                "strong_trend": 0.10,
                "weak_trend": 0.05,
                "high_strength": 0.70,
                "medium_strength": 0.50
            }
        }

    def update_configuration(self, **kwargs):
        """вњ… РќРћР’РћР•: РћР±РЅРѕРІР»РµРЅРёРµ РїР°СЂР°РјРµС‚СЂРѕРІ Р°РЅР°Р»РёР·Р°С‚РѕСЂР°"""
        valid_params = {
            'w_daily', 'w_h4', 'ema_fast', 'ema_slow', 
            'momentum_lookback', 'vol_window', 'atr_period'
        }
        
        updated = []
        for param, value in kwargs.items():
            if param in valid_params:
                private_name = f"_{param}"
                if hasattr(self, private_name):
                    setattr(self, private_name, value)
                    updated.append(param)
                    
        if updated:
            logging.info(f"рџ“Љ Market analyzer updated parameters: {updated}")
        
        return updated








