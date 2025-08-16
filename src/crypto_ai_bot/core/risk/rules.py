from __future__ import annotations
from typing import Tuple, Dict, Any, Optional

# ------------------------------
# Helpers
# ------------------------------

def _ctx(decision: Dict[str, Any]) -> Dict[str, Any]:
    return (decision or {}).get("explain", {}).get("context", {}) or {}

def _get(d: Dict[str, Any], key: str, default: Optional[float] = None) -> Optional[float]:
    v = d.get(key, default)
    try:
        return float(v) if v is not None else None
    except Exception:
        return default

# ------------------------------
# Atomic risk checks (pure functions)
# Each returns (ok: bool, reason: str)
# If required inputs are missing, return (True, "")
# ------------------------------

def check_time_sync(*, drift_ms: int, limit_ms: int) -> Tuple[bool, str]:
    """Block trading when local clock drift exceeds limit."""
    if drift_ms <= limit_ms:
        return True, ""
    return False, f"time_drift_exceeded:{drift_ms}>{limit_ms}"

def check_hours(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """Optional: allow trading only within [start,end). If not configured -> pass."""
    start = int(getattr(cfg, "TRADING_START_HOUR", 0))
    end = int(getattr(cfg, "TRADING_END_HOUR", 24))
    if start <= 0 and end >= 24:
        return True, ""
    hour = _get(_ctx(decision), "hour")
    if hour is None:
        return True, ""
    if start <= int(hour) < end:
        return True, ""
    return False, f"blocked_by_hours:{hour}"

def check_spread(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """Fail if current spread percentage is above limit."""
    limit = float(getattr(cfg, "MAX_SPREAD_PCT", 0.30))  # percent
    c = _ctx(decision)
    spread_pct = _get(c, "spread_pct") or _get(decision, "spread_pct")
    if spread_pct is None:
        return True, ""
    if spread_pct <= limit:
        return True, ""
    return False, f"spread_too_wide:{spread_pct:.4f}>{limit:.4f}"

def check_dd(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """Daily drawdown cap (percentage)."""
    limit = float(getattr(cfg, "MAX_DRAWDOWN_PCT", 5.0))
    dd = _get(_ctx(decision), "day_drawdown_pct")
    if dd is None:
        return True, ""
    if dd <= limit:
        return True, ""
    return False, f"day_dd_exceeded:{dd:.4f}>{limit:.4f}"

def check_seq_losses(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """Stop trading after N consecutive losses (rolling)."""
    limit = int(getattr(cfg, "MAX_SEQ_LOSSES", 5))
    seq = _get(_ctx(decision), "seq_losses")
    if seq is None:
        return True, ""
    if int(seq) <= limit:
        return True, ""
    return False, f"seq_losses_exceeded:{int(seq)}>{limit}"

def check_max_exposure(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """Cap overall exposure either by pct of equity or absolute USD."""
    c = _ctx(decision)
    exp_pct = _get(c, "exposure_pct")
    exp_usd = _get(c, "exposure_usd")
    lim_pct = float(getattr(cfg, "MAX_EXPOSURE_PCT", 100.0))  # percent of equity
    lim_usd = _get(vars(cfg), "MAX_EXPOSURE_USD")  # may be None

    # If nothing known about exposure -> pass
    if exp_pct is None and exp_usd is None:
        return True, ""

    if exp_pct is not None and exp_pct > lim_pct:
        return False, f"exposure_pct_exceeded:{exp_pct:.4f}>{lim_pct:.4f}"

    if lim_usd is not None and exp_usd is not None and exp_usd > float(lim_usd):
        return False, f"exposure_usd_exceeded:{exp_usd:.2f}>{float(lim_usd):.2f}"

    return True, ""
