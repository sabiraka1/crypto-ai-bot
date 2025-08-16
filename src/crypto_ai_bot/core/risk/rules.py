from __future__ import annotations
from typing import Tuple, Dict, Any
from decimal import Decimal

def check_time_sync(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """Return (ok, reason). Uses utils.time_sync if available; otherwise ok=True."""
    limit = int(getattr(cfg, 'TIME_DRIFT_MAX_MS', 1500))
    try:
        from crypto_ai_bot.utils import time_sync
        drift = int(time_sync.get_cached_drift_ms(default=0))
        if drift > limit:
            return False, f'time_drift_exceeded:{drift}ms>{limit}ms'
        return True, 'ok'
    except Exception:
        return True, 'no_time_sync_module'

def check_size_limits(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    max_size = Decimal(str(getattr(cfg, 'MAX_ORDER_SIZE', '10')))
    size = Decimal(str(decision.get('size') or '0')).copy_abs()
    if size > max_size:
        return False, f'max_order_size_exceeded:{size}>{max_size}'
    return True, 'ok'
