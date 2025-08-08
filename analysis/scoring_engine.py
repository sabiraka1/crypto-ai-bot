import os
import math
import numpy as np
import pandas as pd
from typing import Tuple, Dict, Any, Optional


class ScoringEngine:
    """
    Единый движок скоринга:
    - Buy Score: MACD (до 2 баллов) + RSI (1 балл)
    - AI Score: подаётся извне (0..1), если нет — дефолт 0.50
    - Порог входа управляется через .env MIN_SCORE_TO_BUY (по умолчанию 1.4)
    - Размер позиции определяется по AI Score (адаптивная сетка)
    """

    def __init__(self, min_score_to_buy: Optional[float] = None):
        self.min_score_to_buy = (
            float(os.getenv("MIN_SCORE_TO_BUY", "1.4"))
            if min_score_to_buy is None
            else float(min_score_to_buy)
        )

    # ---------- публичный API ----------

    def evaluate(
        self,
        df: pd.DataFrame,
        ai_score: Optional[float] = None
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        Возвращает:
        - buy_score (float)
        - ai_score (float 0..1)
        - details (dict)  -> пригодно для телеграм-уведомлений
        Ожидается df с колонкой 'close' и индексом по времени.
        """
        if df is None or df.empty or "close" not in df.columns:
            # пустые данные — нулевой скоринг
            return 0.0, float(ai_score or 0.5), {
                "reason": "empty_df",
                "rsi": None,
                "macd_hist": None,
                "macd_growing": None,
            }

        rsi_val = self._rsi(df["close"], period=14)
        macd_hist, macd_growing = self._macd_hist_and_growing(df["close"])

        buy_score = 0.0
        details: Dict[str, Any] = {
            "rsi": rsi_val,
            "macd_hist": macd_hist,
            "macd_growing": macd_growing,
        }

        # --- MACD ---
        if macd_hist is not None:
            if macd_hist > 0:
                buy_score += 1.0
            if macd_growing:
                buy_score += 1.0

        # --- RSI (здоровая зона 45..65) ---
        if rsi_val is not None and 45 <= rsi_val <= 65:
            buy_score += 1.0

        # --- AI ---
        ai = float(ai_score) if ai_score is not None else 0.50
        details["ai_score"] = ai
        details["buy_score_components"] = {
            "macd_component": 1.0 if (macd_hist is not None and macd_hist > 0) else 0.0,
            "macd_growing_component": 1.0 if macd_growing else 0.0,
            "rsi_component": 1.0 if (rsi_val is not None and 45 <= rsi_val <= 65) else 0.0,
        }
        details["buy_score_total"] = buy_score
        details["min_score_to_buy"] = self.min_score_to_buy

        return buy_score, ai, details

    def position_fraction(self, ai_score: float) -> float:
        """
        Сетка размера позиции по AI Score:
        >= 0.70 -> 1.00 (100%)
        0.60..0.70 -> 0.90 (90%)
        0.50..0.60 -> 0.60 (60%)
        < 0.50 -> 0.00 (не входим)
        """
        if ai_score >= 0.70:
            return 1.00
        if ai_score >= 0.60:
            return 0.90
        if ai_score >= 0.50:
            return 0.60
        return 0.00

    # ---------- служебные методы ----------

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
        # фильтрация NaN/Inf
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
        Возвращает (histogram_last, is_growing)
        hist>0 даёт 1 балл, рост hist (последний > предыдущего) даёт ещё 1 балл.
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
