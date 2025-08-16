from __future__ import annotations

from typing import Tuple, Dict, Any, Optional
from decimal import Decimal

# Friendly rule keys that will appear in Decision.explain.blocks
RULE_DISABLED = "disabled"
RULE_HOURS = "hours"
RULE_SPREAD = "spread"
RULE_DRAWDOWN = "max_drawdown"
RULE_SEQ_LOSSES = "seq_losses"
RULE_EXPOSURE = "max_exposure"
# (Optional/advanced rules could be added later: "time_drift", "volatility", "news_blackout", ...)

def _get_ctx(decision: Dict[str, Any]) -> Dict[str, Any]:
    exp = decision.get("explain") or {}
    return exp.get("context") or {}

def _pct(v: Optional[float]) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None

def _num(v) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None

# ---------------- rules ----------------

def check_disabled(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    # hard switches
    if bool(getattr(cfg, "SAFE_MODE", False)):
        return False, f"{RULE_DISABLED}: SAFE_MODE"
    if not bool(getattr(cfg, "ENABLE_TRADING", False)):
        return False, f"{RULE_DISABLED}: trading_disabled"
    return True, "ok"

def check_hours(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    ctx = _get_ctx(decision)
    hour = int(ctx.get("hour", -1))
    start = int(getattr(cfg, "TRADING_START_HOUR", 0))
    end = int(getattr(cfg, "TRADING_END_HOUR", 24))
    if start <= end:
        ok = (start <= hour < end)
    else:
        # overnight window e.g. 22..2
        ok = (hour >= start or hour < end)
    if not ok:
        return False, f"{RULE_HOURS}: hour={hour} not in [{start},{end}) UTC"
    return True, "ok"

def check_spread(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    ctx = _get_ctx(decision)
    spread = _pct(ctx.get("spread_pct"))
    max_spread = _pct(getattr(cfg, "MAX_SPREAD_PCT", None))
    if spread is None or max_spread is None:
        return True, "ok"  # no data or not configured → skip
    if spread > max_spread:
        return False, f"{RULE_SPREAD}: {spread:.2f}%>{max_spread:.2f}%"
    return True, "ok"

def check_drawdown(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    ctx = _get_ctx(decision)
    dd = _pct(ctx.get("day_drawdown_pct"))
    max_dd = _pct(getattr(cfg, "MAX_DRAWDOWN_PCT", None))
    if dd is None or max_dd is None:
        return True, "ok"
    if dd > max_dd:
        return False, f"{RULE_DRAWDOWN}: {dd:.2f}%>{max_dd:.2f}%"
    return True, "ok"

def check_seq_losses(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    ctx = _get_ctx(decision)
    seq = ctx.get("seq_losses")
    try:
        seq = int(seq) if seq is not None else None
    except Exception:
        seq = None
    max_seq = int(getattr(cfg, "MAX_SEQ_LOSSES", 0) or 0)
    if seq is None or max_seq <= 0:
        return True, "ok"
    if seq > max_seq:
        return False, f"{RULE_SEQ_LOSSES}: {seq}>{max_seq}"
    return True, "ok"

def check_exposure(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    ctx = _get_ctx(decision)
    exp_pct = _pct(ctx.get("exposure_pct"))
    exp_usd = _num(ctx.get("exposure_usd"))
    max_pct = _pct(getattr(cfg, "MAX_EXPOSURE_PCT", None))
    max_usd = _num(getattr(cfg, "MAX_EXPOSURE_USD", None))

    # Prefer percentage limit if both configured
    if max_pct is not None and exp_pct is not None:
        if exp_pct > max_pct:
            return False, f"{RULE_EXPOSURE}: {exp_pct:.2f}%>{max_pct:.2f}%"
        return True, "ok"

    if max_usd is not None and exp_usd is not None:
        if exp_usd > max_usd:
            return False, f"{RULE_EXPOSURE}: ${exp_usd:.2f}>${max_usd:.2f}"
        return True, "ok"

    return True, "ok"

# master check (ordered)
def check(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    # Order matters — earliest failure reported
    for fn in (check_disabled, check_hours, check_spread, check_drawdown, check_seq_losses, check_exposure):
        ok, reason = fn(decision, cfg)
        if not ok:
            return False, reason
    return True, "ok"
