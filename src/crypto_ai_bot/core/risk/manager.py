from __future__ import annotations

from typing import Tuple, Dict, Any, Optional

from . import rules

def check(features: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """
    Последовательная проверка правил. Возвращает (ok, reason).
    reason в формате "rule: detail", где rule ∈
      {"disabled","hours","spread","max_drawdown","seq_losses","max_exposure","time_drift"}
    features может содержать:
      - "spread_pct"
      - "day_drawdown_pct"
      - "seq_losses"
      - "exposure_pct", "exposure_usd"
    """
    # 1) trading disabled
    ok, detail = rules.check_disabled(safe_mode=bool(getattr(cfg, "SAFE_MODE", False)),
                                      enable_trading=bool(getattr(cfg, "ENABLE_TRADING", True)))
    if not ok: return False, f"disabled: {detail}"

    # 2) time drift
    ok, detail = rules.check_time_drift(drift_ms_limit=int(getattr(cfg, "TIME_DRIFT_MAX_MS", 1500)))
    if not ok: return False, f"time_drift: {detail}"

    # 3) hours
    ok, detail = rules.check_hours(start_hour=int(getattr(cfg, "TRADING_START_HOUR", 0)),
                                   end_hour=int(getattr(cfg, "TRADING_END_HOUR", 24)))
    if not ok: return False, f"hours: {detail}"

    # 4) spread
    ok, detail = rules.check_spread(spread_pct=features.get("spread_pct"),
                                    max_spread_pct=float(getattr(cfg, "MAX_SPREAD_PCT", 0.2)))
    if not ok: return False, f"spread: {detail}"

    # 5) daily drawdown
    ok, detail = rules.check_max_drawdown(day_drawdown_pct=features.get("day_drawdown_pct"),
                                          max_drawdown_pct=float(getattr(cfg, "MAX_DRAWDOWN_PCT", 5.0)))
    if not ok: return False, f"max_drawdown: {detail}"

    # 6) sequential losses
    ok, detail = rules.check_seq_losses(seq_losses=features.get("seq_losses"),
                                        max_seq_losses=int(getattr(cfg, "MAX_SEQ_LOSSES", 3)))
    if not ok: return False, f"seq_losses: {detail}"

    # 7) exposure
    ok, detail = rules.check_max_exposure(exposure_pct=features.get("exposure_pct"),
                                          max_exposure_pct=getattr(cfg, "MAX_EXPOSURE_PCT", None),
                                          exposure_usd=features.get("exposure_usd"),
                                          max_exposure_usd=getattr(cfg, "MAX_EXPOSURE_USD", None))
    if not ok: return False, f"max_exposure: {detail}"

    return True, ""
