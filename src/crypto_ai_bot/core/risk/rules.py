from __future__ import annotations
from typing import Tuple, Optional
from decimal import Decimal, InvalidOperation

def _to_dec(v) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")

def check_min_history(bars: Optional[int], min_bars: int) -> Tuple[bool, str]:
    """
    Требуем минимум баров для устойчивых расчётов индикаторов.
    """
    if bars is None:
        return True, "no_bars_info"
    try:
        b = int(bars)
    except Exception:
        return True, "bars_unknown"
    if b < int(min_bars):
        return False, f"min_history:{b}<{min_bars}"
    return True, "ok"

def check_max_exposure(exposure_units, max_units) -> Tuple[bool, str]:
    """
    Ограничиваем суммарную экспозицию в базовой валюте (сумма |size| по открытым позициям).
    """
    exp = _to_dec(exposure_units)
    lim = _to_dec(max_units)
    if lim <= 0:
        return True, "limit_disabled"
    if exp.copy_abs() > lim:
        return False, f"exposure:{exp}>{lim}"
    return True, "ok"

def check_time_sync(drift_ms: Optional[int], limit_ms: int) -> Tuple[bool, str]:
    """
    Защита от рассинхронизации времени. Если drift_ms неизвестен — не блокируем.
    """
    if drift_ms is None:
        return True, "no_drift_info"
    try:
        d = int(drift_ms)
    except Exception:
        return True, "drift_unknown"
    if d > int(limit_ms):
        return False, f"time_drift:{d}>{limit_ms}"
    return True, "ok"
