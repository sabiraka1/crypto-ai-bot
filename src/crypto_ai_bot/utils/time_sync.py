from __future__ import annotations
import time

def measure_time_drift_ms(container) -> int:
    """
    Сравниваем локальное время и брокерское (через ccxt, если доступно).
    Если нет – считаем 0 (не валим health).
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
