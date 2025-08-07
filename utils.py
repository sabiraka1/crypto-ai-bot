# utils.py

import numpy as np

def detect_support_resistance(df, window=10):
    """
    Простое определение уровней поддержки и сопротивления:
    - поддержка = локальные минимумы
    - сопротивление = локальные максимумы
    """
    if len(df) < window * 2:
        last_price = df["close"].iloc[-1]
        return last_price * 0.98, last_price * 1.02

    support = df["low"].rolling(window=window).min().iloc[-1]
    resistance = df["high"].rolling(window=window).max().iloc[-1]

    return support, resistance
