from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Tuple, Optional

@dataclass(frozen=True)
class RuleResult:
    ok: bool
    reason: str = ""

# --- Pure, IO-free rule checks ---

def check_time_drift(drift_ms: Optional[int], limit_ms: int) -> RuleResult:
    """
    Блокируем торговлю, если системные часы «уплыли».
    Если drift_ms = None (неизвестно) — НЕ блокируем (правило нейтрально).
    """
    if drift_ms is None:
        return RuleResult(True, "")
    try:
        d = int(drift_ms)
        lim = int(limit_ms)
    except Exception:
        return RuleResult(True, "")
    if d > lim:
        return RuleResult(False, f"time_drift_exceeded: {d}ms > {lim}ms")
    return RuleResult(True, "")

def check_spread(spread_pct: Optional[float], max_spread_pct: float) -> RuleResult:
    if spread_pct is None:
        return RuleResult(True, "")
    try:
        s = float(spread_pct)
        lim = float(max_spread_pct)
    except Exception:
        return RuleResult(True, "")
    if s > lim:
        return RuleResult(False, f"spread_too_wide: {s:.4f}% > {lim:.4f}%")
    return RuleResult(True, "")

def check_hours(start_hour: int, end_hour: int) -> RuleResult:
    """
    Разрешаем торги только в окне [start_hour, end_hour).
    Если start=0,end=24 — всегда ок.
    """
    try:
        sh = int(start_hour); eh = int(end_hour)
    except Exception:
        return RuleResult(True, "")
    if sh <= 0 and eh >= 24:
        return RuleResult(True, "")

    now_h = datetime.now(timezone.utc).hour
    if sh <= eh:
        ok = (sh <= now_h < eh)
    else:
        # окно через полночь, например 22..6
        ok = (now_h >= sh or now_h < eh)

    if not ok:
        return RuleResult(False, f"out_of_trading_hours: now_utc_hour={now_h}, window=[{sh},{eh})")
    return RuleResult(True, "")

def check_drawdown(drawdown_pct: Optional[float], max_dd_pct: float) -> RuleResult:
    if drawdown_pct is None:
        return RuleResult(True, "")
    try:
        d = float(drawdown_pct)
        lim = float(max_dd_pct)
    except Exception:
        return RuleResult(True, "")
    if d > lim:
        return RuleResult(False, f"max_drawdown_exceeded: {d:.4f}% > {lim:.4f}%")
    return RuleResult(True, "")

def check_seq_losses(seq_losses: Optional[int], max_losses: int) -> RuleResult:
    if seq_losses is None:
        return RuleResult(True, "")
    try:
        s = int(seq_losses)
        lim = int(max_losses)
    except Exception:
        return RuleResult(True, "")
    if s > lim:
        return RuleResult(False, f"too_many_consecutive_losses: {s} > {lim}")
    return RuleResult(True, "")

def check_max_exposure(exposure_pct: Optional[float], exposure_usd: Optional[float],
                       max_pct: Optional[float], max_usd: Optional[float]) -> RuleResult:
    # Проверяем оба лимита, если заданы
    if max_pct is not None and exposure_pct is not None:
        try:
            e = float(exposure_pct)
            lim = float(max_pct)
            if e > lim:
                return RuleResult(False, f"max_exposure_pct_exceeded: {e:.4f}% > {lim:.4f}%")
        except Exception:
            pass
    if max_usd is not None and exposure_usd is not None:
        try:
            e = float(exposure_usd)
            lim = float(max_usd)
            if e > lim:
                return RuleResult(False, f"max_exposure_usd_exceeded: {e:.2f} > {lim:.2f}")
        except Exception:
            pass
    return RuleResult(True, "")
