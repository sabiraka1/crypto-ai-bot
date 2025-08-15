import os
import math
import numpy as np
import pandas as pd
from typing import Tuple, Dict, Any, Optional


class ScoringEngine:
    """
    вњ… РРЎРџР РђР’Р›Р•РќРћ: Р•РґРёРЅС‹Р№ РґРІРёР¶РѕРє СЃРєРѕСЂРёРЅРіР° СЃ СѓРЅРёС„РёС†РёСЂРѕРІР°РЅРЅС‹Рј API:
    - Buy Score (РЅРѕСЂРјРёСЂРѕРІР°РЅ РІ [0..1]): MACD (РґРѕ 2 Р±Р°Р»Р»РѕРІ) + RSI (1 Р±Р°Р»Р») в†’ raw 0..3 в†’ /3
    - AI Score: РїРѕРґР°С‘С‚СЃСЏ РёР·РІРЅРµ (0..1), РµСЃР»Рё РЅРµС‚ вЂ” РґРµС„РѕР»С‚ 0.50
    - РџРѕСЂРѕРі РІС…РѕРґР° Р·Р°РґР°С‘С‚СЃСЏ С‡РµСЂРµР· .env MIN_SCORE_TO_BUY (РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ 0.65, С‚Р°Рє РєР°Рє now [0..1])
    - Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё РѕРїСЂРµРґРµР»СЏРµС‚СЃСЏ РїРѕ AI Score (РґРёСЃРєСЂРµС‚РЅР°СЏ СЃРµС‚РєР° РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ; РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ Р»РёРЅРµР№РЅРѕ)
    """

    def __init__(self, min_score_to_buy: Optional[float] = None):
        # РїРѕСЂРѕРі РІ РЅРѕСЂРјР°Р»РёР·РѕРІР°РЅРЅРѕР№ С€РєР°Р»Рµ [0..1]
        self.min_score_to_buy = (
            float(os.getenv("MIN_SCORE_TO_BUY", "0.65"))
            if min_score_to_buy is None
            else float(min_score_to_buy)
        )
        # СЂРµР¶РёРј Рё РїР°СЂР°РјРµС‚СЂС‹ СЃР°Р№Р·РёРЅРіР°
        self.pos_mode = (os.getenv("AI_POSITION_MODE", "step").strip().lower() or "step")
        self.pos_min = float(os.getenv("POSITION_MIN_FRACTION", "0.30"))  # РґР»СЏ linear
        self.pos_max = float(os.getenv("POSITION_MAX_FRACTION", "1.00"))  # РґР»СЏ linear

    # ---------- РїСѓР±Р»РёС‡РЅС‹Р№ API (СѓРЅРёС„РёС†РёСЂРѕРІР°РЅРЅС‹Р№) ----------

    def evaluate(
        self,
        df: pd.DataFrame,
        ai_score: Optional[float] = None
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        вњ… РћРЎРќРћР’РќРћР™ РњР•РўРћР”: Р’РѕР·РІСЂР°С‰Р°РµС‚:
        - buy_score_norm (float РІ [0..1])
        - ai_score (float 0..1)
        - details (dict)  -> РїСЂРёРіРѕРґРЅРѕ РґР»СЏ С‚РµР»РµРіСЂР°Рј-СѓРІРµРґРѕРјР»РµРЅРёР№ Рё Р»РѕРіРѕРІ
        РћР¶РёРґР°РµС‚СЃСЏ df СЃ РєРѕР»РѕРЅРєРѕР№ 'close' Рё РёРЅРґРµРєСЃРѕРј РїРѕ РІСЂРµРјРµРЅРё.
        """
        if df is None or df.empty or "close" not in df.columns:
            return 0.0, float(ai_score or 0.5), {
                "reason": "empty_df",
                "rsi": None,
                "macd_hist": None,
                "macd_growing": None,
                "buy_score_raw": 0.0,
                "buy_score_norm": 0.0,
                "min_score_to_buy": self.min_score_to_buy,
            }

        rsi_val = self._rsi(df["close"], period=14)
        macd_hist, macd_growing = self._macd_hist_and_growing(df["close"])

        buy_raw = 0.0
        # --- MACD ---
        if macd_hist is not None:
            if macd_hist > 0:
                buy_raw += 1.0
            if macd_growing:
                buy_raw += 1.0
        # --- RSI (Р·РґРѕСЂРѕРІР°СЏ Р·РѕРЅР° 45..65) ---
        if rsi_val is not None and 45 <= rsi_val <= 65:
            buy_raw += 1.0

        buy_norm = float(max(0.0, min(1.0, buy_raw / 3.0)))

        ai = float(ai_score) if ai_score is not None else 0.50

        details: Dict[str, Any] = {
            "rsi": rsi_val,
            "macd_hist": macd_hist,
            "macd_growing": macd_growing,
            "ai_score": ai,
            "buy_score_components": {
                "macd_component": 1.0 if (macd_hist is not None and macd_hist > 0) else 0.0,
                "macd_growing_component": 1.0 if macd_growing else 0.0,
                "rsi_component": 1.0 if (rsi_val is not None and 45 <= rsi_val <= 65) else 0.0,
            },
            "buy_score_raw": buy_raw,
            "buy_score_norm": buy_norm,
            "min_score_to_buy": self.min_score_to_buy,
            "market_condition": self._guess_market_condition(df),
            "pattern": ""  # Р—Р°РіР»СѓС€РєР° РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё
        }

        return buy_norm, ai, details

    def position_fraction(self, ai_score: float) -> float:
        """
        Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё РЅР° РѕСЃРЅРѕРІРµ AI Score.

        Р РµР¶РёРјС‹:
        - step (РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ):
            >= 0.70 -> 1.00 (100%)
            0.60..0.70 -> 0.90 (90%)
            0.50..0.60 -> 0.60 (60%)
            < 0.50 -> 0.00 (РЅРµ РІС…РѕРґРёРј)
        - linear (РІРєР»СЋС‡РёС‚СЊ С‡РµСЂРµР· AI_POSITION_MODE=linear):
            Р»РёРЅРµР№РЅР°СЏ С€РєР°Р»Р° РІ [POSITION_MIN_FRACTION..POSITION_MAX_FRACTION]
            РїСЂРё ai_score=0.0 -> min, ai_score=1.0 -> max
        """
        ai = float(ai_score or 0.0)
        ai = max(0.0, min(1.0, ai))

        if self.pos_mode == "linear":
            mn = max(0.0, min(1.0, self.pos_min))
            mx = max(0.0, min(1.0, self.pos_max))
            if mx < mn:
                mn, mx = mx, mn
            return mn + (mx - mn) * ai

        # step mode (РґРµС„РѕР»С‚)
        if ai >= 0.70:
            return 1.00
        if ai >= 0.60:
            return 0.90
        if ai >= 0.50:
            return 0.60
        return 0.00

    # ---------- СЃР»СѓР¶РµР±РЅС‹Рµ РјРµС‚РѕРґС‹ ----------

    def _rsi(self, close: pd.Series, period: int = 14) -> Optional[float]:
        if close is None or len(close) < period + 1:
            return None
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)

        roll_up = gain.ewm(alpha=1/period, adjust=False).mean()
        roll_down = loss.ewm(alpha=1/period, adjust=False).mean()

        rs = roll_up / (roll_down + 1e-12)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        val = float(rsi.iloc[-1])
        if not np.isfinite(val):
            return None
        return val

    def _macd_hist_and_growing(
        self,
        close: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Tuple[Optional[float], bool]:
        """
        Р’РѕР·РІСЂР°С‰Р°РµС‚ (histogram_last, is_growing)
        hist>0 РґР°С‘С‚ 1 Р±Р°Р»Р», СЂРѕСЃС‚ hist (РїРѕСЃР»РµРґРЅРёР№ > РїСЂРµРґС‹РґСѓС‰РµРіРѕ) РґР°С‘С‚ РµС‰С‘ 1 Р±Р°Р»Р».
        """
        if close is None or len(close) < slow + signal + 2:
            return None, False

        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal, adjust=False).mean()
        hist = macd - macd_signal

        last = float(hist.iloc[-1])
        prev = float(hist.iloc[-2])
        if not (np.isfinite(last) and np.isfinite(prev)):
            return None, False

        is_growing = last > prev
        return last, is_growing

    def _guess_market_condition(self, df: pd.DataFrame) -> str:
        """РџСЂРѕСЃС‚Р°СЏ РѕС†РµРЅРєР° СЂС‹РЅРѕС‡РЅС‹С… СѓСЃР»РѕРІРёР№ РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё"""
        try:
            if df.empty or len(df) < 50:
                return "sideways"
            
            close = df["close"]
            ema_20 = close.ewm(span=20).mean().iloc[-1]
            ema_50 = close.ewm(span=50).mean().iloc[-1]
            
            if np.isnan(ema_20) or np.isnan(ema_50):
                return "sideways"
                
            if ema_20 > ema_50 * 1.005:  # 0.5% РІС‹С€Рµ
                return "bull"
            elif ema_20 < ema_50 * 0.995:  # 0.5% РЅРёР¶Рµ
                return "bear"
            else:
                return "sideways"
        except Exception:
            return "sideways"

    # ---- вњ… РРЎРџР РђР’Р›Р•РќРћ: РћР±СЂР°С‚РЅР°СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ СЃ СѓРЅРёС„РёС†РёСЂРѕРІР°РЅРЅС‹РјРё РјРµС‚РѕРґР°РјРё ----
    
    def score(self, df, ai_score=None):
        """РЎРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ: РІРѕР·РІСЂР°С‰Р°РµС‚ (buy_score_norm, ai_score, details)."""
        return self.evaluate(df, ai_score=ai_score)

    def calculate_scores(self, df, ai_score=None):
        """РЈРЅРёС„РёС†РёСЂРѕРІР°РЅРЅР°СЏ С‚РѕС‡РєР° РІС…РѕРґР°. Р’РѕР·РІСЂР°С‰Р°РµС‚ (buy_score_norm, ai_score, details)."""
        return self.evaluate(df, ai_score=ai_score)








