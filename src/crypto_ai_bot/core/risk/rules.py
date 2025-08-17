from __future__ import annotations
from typing import Tuple, Optional


def ok(reason: str = "ok") -> Tuple[bool, str]:
    return True, reason


def fail(reason: str) -> Tuple[bool, str]:
    return False, reason


def check_time_sync(time_drift_ms: Optional[int], limit_ms: int) -> Tuple[bool, str]:
    """
    Блокируем торговлю при рассинхронизации локального времени и эталона.
    Если нет данных (None) — правило пропускаем (ok).
    """
    if time_drift_ms is None:
        return ok("no_drift_data")
    if time_drift_ms > limit_ms:
        return fail(f"time_drift_exceeded:{time_drift_ms}ms>{limit_ms}ms")
    return ok()


def check_min_history(bars: Optional[int], min_bars: int) -> Tuple[bool, str]:
    """
    Минимально необходимая глубина истории для расчёта индикаторов.
    """
    if bars is None:
        return ok("no_bars_info")
    if bars < min_bars:
        return fail(f"not_enough_bars:{bars}<{min_bars}")
    return ok()
