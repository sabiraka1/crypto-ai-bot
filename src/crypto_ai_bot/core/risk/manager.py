from __future__ import annotations
from typing import Tuple, Dict, Any, Callable, List

from crypto_ai_bot.core.risk.rules import (
    check_time_sync,
    check_hours,
    check_spread,
    check_dd,
    check_seq_losses,
    check_max_exposure,
)

# Ordered list of (rule_name, callable(decision,cfg)->(ok,reason))
_RULES: List[tuple[str, Callable[[Dict[str, Any], Any], tuple[bool, str]]]] = [
    ("hours",          check_hours),
    ("spread",         check_spread),
    ("drawdown",       check_dd),
    ("seq_losses",     check_seq_losses),
    ("max_exposure",   check_max_exposure),
]

def check(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """Aggregate all risk checks. Returns (ok, reason).

    NOTE: time_sync is evaluated first and independently, as it does not require 'decision'.

    All other rules are *data-aware*: if required fields are missing, they pass.

    """
    # Time drift (global)
    try:
        from crypto_ai_bot.utils.time_sync import get_cached_drift_ms
        drift = int(get_cached_drift_ms(0))
    except Exception:
        drift = 0
    limit = int(getattr(cfg, "TIME_DRIFT_MAX_MS", 1500))
    ok, reason = check_time_sync(drift_ms=drift, limit_ms=limit)
    if not ok:
        return False, reason

    # Rule chain
    for name, fn in _RULES:
        try:
            ok, reason = fn(decision, cfg)
        except TypeError:
            # backwards compatibility if fn signature differs
            ok, reason = fn(decision=decision, cfg=cfg)  # type: ignore
        if not ok:
            return False, f"{name}:{reason}"

    return True, ""
