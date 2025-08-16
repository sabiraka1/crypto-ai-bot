from __future__ import annotations

from decimal import Decimal
from typing import Tuple, Optional

def check_time_sync(drift_ms: int, limit_ms: int) -> Tuple[bool, str]:
    """
    Блокируем торговлю при сильном рассинхроне системных часов.
    :param drift_ms: измеренный дрейф (мс), |local_utc - reference_utc|
    :param limit_ms: допустимый порог (мс), например 1000
    :return: (ok, reason)
    """
    try:
        d = int(drift_ms)
        lim = int(limit_ms)
    except Exception:
        # если не можем распарсить значения — лучше блокировать с понятным reason
        return False, "time_sync:invalid_drift_values"
    if d <= lim:
        return True, ""
    return False, f"time_sync:drift_ms={d}>limit_ms={lim}"


def check_max_exposure(current_exposure: Decimal, max_exposure: Decimal) -> Tuple[bool, str]:
    """
    Простая проверка общего объёма риска в позициях.
    :param current_exposure: текущее экспозиция (в quote), Decimal
    :param max_exposure: лимит экспозиции (в quote), Decimal
    """
    try:
        if current_exposure <= max_exposure:
            return True, ""
        return False, f"exposure:{current_exposure}>{max_exposure}"
    except Exception:
        # в сомнительных случаях безопаснее заблокировать
        return False, "exposure:invalid_values"


def check_seq_losses(loss_streak: int, max_streak: int) -> Tuple[bool, str]:
    """
    Ограничение серии убыточных сделок подряд.
    """
    try:
        if int(loss_streak) <= int(max_streak):
            return True, ""
        return False, f"seq_losses:{loss_streak}>{max_streak}"
    except Exception:
        return False, "seq_losses:invalid_values"
