from __future__ import annotations
from typing import Optional, Dict, Any
import time

def _now_ms() -> int:
    return int(time.time() * 1000)

def measure_time_drift_ms(broker: Any) -> Dict[str, Any]:
    """
    Пробуем получить серверное время биржи и вернуть дрейф в мс.
    Порядок: broker.ccxt.fetch_time() -> broker.ccxt.milliseconds() -> 0.
    """
    ex = getattr(broker, "ccxt", None)
    server_ms: Optional[int] = None
    try:
        if ex and hasattr(ex, "fetch_time"):
            t = ex.fetch_time()
            if isinstance(t, (int, float)):
                server_ms = int(t)
    except Exception:
        pass
    if server_ms is None:
        try:
            if ex and hasattr(ex, "milliseconds"):
                server_ms = int(ex.milliseconds())
        except Exception:
            server_ms = None
    local_ms = _now_ms()
    if server_ms is None:
        return {"ok": False, "drift_ms": 0, "source": "none"}
    return {"ok": True, "drift_ms": int(abs(local_ms - server_ms)), "source": "exchange"}
