# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations
from typing import Any, Tuple

from crypto_ai_bot.utils import time_sync as ts


def check_time_sync(cfg) -> Tuple[bool, str]:
    """Блокируем торговлю при слишком большом расхождении часов."""
    limit = int(getattr(cfg, "TIME_DRIFT_MAX_MS", 1500))
    drift = ts.get_cached_drift_ms(0)
    if abs(drift) > limit:
        return False, f"time_drift_ms={drift}>limit={limit}"
    return True, "ok"
