import os
import math
import numpy as np
import pandas as pd
from typing import Tuple, Dict, Any, Optional


class ScoringEngine:
    """
    Единый движок скоринга:
    - Buy Score (нормирован в [0..1]): MACD (до 2 баллов) + RSI (1 балл) → raw 0..3 → /3
    - AI Score: подаётся извне (0..1), если нет — дефолт 0.50
    - Порог входа задаётся через .env MIN_SCORE_TO_BUY (по умолчанию 0.65, так как now [0..1])
    - Размер позиции определяется по AI Score (дискретная сетка по умолчанию; опционально линейно)
    """

    def __init__(self, min_score_to_buy: Optional[float] = None):
        # порог в нормализованной шкале [0..1]
        self.min_score_to_buy = (
            float(os.getenv("MIN_SCORE_TO_BUY", "0.65"))
            if min_score_to_buy is None
            else float(min_score_to_buy)
        )
        # режим и параметры сайзинга
        self.pos_mode = (os.getenv("AI_POSITION_MODE", "step").strip().lower() or "step")
        self.pos_min = float(os.getenv("POSITION_MIN_FRACTION", "0.30"))  # для linear
        self.pos_max = float(os.getenv("POSITION_MAX_FRACTION", "1.00"))  # для linear

    # ---------- публичный API ----------

    def evaluate(
        self,
        df: pd.DataFrame,
        ai_score: Optional[float] = None
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        Возвращает:
        - buy_score_norm (float в [0..1])
        - ai_score (float 0..1)
        - details (dict)  -> пригодно для телеграм-уведомлений и логов
        Ожидается df с колонкой 'close' и индексом по времени.
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
        # --- RSI (здоровая зона 45..65) ---
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
        }

        return buy_norm, ai, details

    def position_fraction(self, ai_score: float) -> float:
        """
        Размер позиции на основе AI Score.

        Режимы:
        - step (по умолчанию):
            >= 0.70 -> 1.00 (100%)
            0.60..0.70 -> 0.90 (90%)
            0.50..0.60 -> 0.60 (60%)
            < 0.50 -> 0.00 (не входим)
        - linear (включить через AI_POSITION_MODE=linear):
            линейная шкала в [POSITION_MIN_FRACTION..POSITION_MAX_FRACTION]
            при ai_score=0.0 -> min, ai_score=1.0 -> max
        """
        ai = float(ai_score or 0.0)
        ai = max(0.0, min(1.0, ai))

        if self.pos_mode == "linear":
            mn = max(0.0, min(1.0, self.pos_min))
            mx = max(0.0, min(1.0, self.pos_max))
            if mx < mn:
                mn, mx = mx, mn
            return mn + (mx - mn) * ai

        # step mode (дефолт)
        if ai >= 0.70:
            return 1.00
        if ai >= 0.60:
            return 0.90
        if ai >= 0.50:
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

    # ---- Backwards compatibility shims ----
    def score(self, df, ai_score=None):
        """Совместимость: возвращает (buy_score_norm, ai_score, details)."""
        return self.evaluate(df, ai_score=ai_score)

    def calculate_scores(self, df, ai_score=None):
        """Унифицированная точка входа. Возвращает (buy_score_norm, ai_score, details)."""
        return self.evaluate(df, ai_score=ai_score)
