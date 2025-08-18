# src/crypto_ai_bot/utils/time_sync.py
from __future__ import annotations
import time

def measure_time_drift_ms(container) -> int:
    """
    Разница локального времени и времени биржи (если ccxt поддерживает).
    Если недоступно — возвращаем 0 (не считаем фэйлом).
    """
    try:
        ccxt = getattr(container.broker, "ccxt", None)
        if ccxt and hasattr(ccxt, "milliseconds"):
            bt = int(ccxt.milliseconds())
            lt = int(time.time() * 1000)
            return abs(bt - lt)
    except Exception:
        pass
    return 0
