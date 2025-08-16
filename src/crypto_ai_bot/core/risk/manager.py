from __future__ import annotations
from typing import Tuple, Dict, Any
from crypto_ai_bot.core.risk.rules import check_time_sync, check_hours

def check(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    try:
        from crypto_ai_bot.utils.time_sync import get_cached_drift_ms
        drift = int(get_cached_drift_ms(0))
    except Exception:
        drift = 0
    limit = int(getattr(cfg, "TIME_DRIFT_MAX_MS", 1500))
    ok, reason = check_time_sync(drift_ms=drift, limit_ms=limit)
    if not ok:
        return False, reason
    ok, reason = check_hours(decision, cfg)
    if not ok:
        return False, reason
    return True, ""