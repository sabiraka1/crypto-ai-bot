from __future__ import annotations
from typing import Tuple, Dict, Any

def check_time_sync(*, drift_ms: int, limit_ms: int) -> Tuple[bool, str]:
    if drift_ms <= limit_ms:
        return True, ""
    return False, f"time_drift_exceeded:{drift_ms}>{limit_ms}"

def check_hours(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    start = int(getattr(cfg, "TRADING_START_HOUR", 0))
    end = int(getattr(cfg, "TRADING_END_HOUR", 24))
    if start <= 0 and end >= 24:
        return True, ""
    hour = decision.get("explain", {}).get("context", {}).get("hour")
    if hour is None:
        return True, ""
    if start <= int(hour) < end:
        return True, ""
    return False, f"blocked_by_hours:{hour}"