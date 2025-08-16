from __future__ import annotations

from typing import Tuple, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime, timezone

# внешние зависимости — мягкие (safe import)
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift  # returns float ms
except Exception:  # pragma: no cover
    def measure_time_drift() -> float:  # type: ignore
        return 0.0

# ---------- helpers ----------

def _pct(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0

def _now_hour_utc() -> int:
    return int(datetime.now(tz=timezone.utc).hour)

# ---------- pure checks (return ok, detail) ----------

def check_disabled(*, safe_mode: bool, enable_trading: bool) -> Tuple[bool, str]:
    if safe_mode or not enable_trading:
        return False, "trading_disabled"
    return True, ""

def check_hours(*, start_hour: int, end_hour: int) -> Tuple[bool, str]:
    """Торговать только в окне [start_hour, end_hour) в UTC"""
    h = _now_hour_utc()
    ok = (h >= int(start_hour)) and (h < int(end_hour))
    return (ok, f"utc_hour={h}, allowed=[{start_hour},{end_hour})") if not ok else (True, "")

def check_spread(*, spread_pct: Optional[float], max_spread_pct: float) -> Tuple[bool, str]:
    if spread_pct is None:
        return True, ""  # нет данных — не блокируем
    ok = float(spread_pct) <= float(max_spread_pct)
    return (ok, f"spread_pct={spread_pct:.4f} > max={max_spread_pct:.4f}") if not ok else (True, "")

def check_max_drawdown(*, day_drawdown_pct: Optional[float], max_drawdown_pct: float) -> Tuple[bool, str]:
    if day_drawdown_pct is None:
        return True, ""
    ok = _pct(day_drawdown_pct) <= _pct(max_drawdown_pct)
    return (ok, f"day_dd_pct={day_drawdown_pct:.4f} > max={max_drawdown_pct:.4f}") if not ok else (True, "")

def check_seq_losses(*, seq_losses: Optional[int], max_seq_losses: int) -> Tuple[bool, str]:
    if seq_losses is None:
        return True, ""
    ok = int(seq_losses) <= int(max_seq_losses)
    return (ok, f"seq_losses={seq_losses} > max={max_seq_losses}") if not ok else (True, "")

def check_max_exposure(*, exposure_pct: Optional[float], max_exposure_pct: Optional[float],
                       exposure_usd: Optional[float], max_exposure_usd: Optional[float]) -> Tuple[bool, str]:
    # приоритет проценту, если и то и то есть
    if max_exposure_pct is not None and exposure_pct is not None:
        ok = _pct(exposure_pct) <= _pct(max_exposure_pct)
        return (ok, f"exposure_pct={exposure_pct:.4f} > max={max_exposure_pct:.4f}") if not ok else (True, "")
    if max_exposure_usd is not None and exposure_usd is not None:
        ok = _pct(exposure_usd) <= _pct(max_exposure_usd)
        return (ok, f"exposure_usd={exposure_usd:.2f} > max={max_exposure_usd:.2f}") if not ok else (True, "")
    return True, ""

def check_time_drift(*, drift_ms_limit: int) -> Tuple[bool, str]:
    """Блокирует торговлю при рассинхронизации времени больше лимита (ms)."""
    try:
        drift = float(measure_time_drift())
    except Exception:
        drift = 0.0
    ok = drift <= float(drift_ms_limit)
    return (ok, f"drift_ms={drift:.0f} > limit={drift_ms_limit}") if not ok else (True, "")
