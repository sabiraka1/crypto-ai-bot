from __future__ import annotations

"""
Чистые функции-проверки риска. Никакого IO/HTTP.
Возвращают tuple[bool, str|None]
"""

from decimal import Decimal
from typing import Any, Dict, Tuple


def _ok() -> Tuple[bool, str | None]:
    return True, None


def check_time_sync(features: Dict[str, Any], cfg) -> Tuple[bool, str | None]:
    """
    Блокирует торговлю при рассинхронизации времени больше лимита.
    Ожидает, что оркестратор/сервер обновит cfg.TIME_DRIFT_MS периодически (через /health).
    """
    limit_ms = int(getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000) or 1000)
    drift_ms = int(getattr(cfg, "TIME_DRIFT_MS", 0) or 0)
    if drift_ms > limit_ms:
        return False, f"time_drift_exceeded:{drift_ms}ms>{limit_ms}ms"
    return _ok()


def check_max_exposure(features: Dict[str, Any], cfg) -> Tuple[bool, str | None]:
    """
    Ограничение по максимальной совокупной экспозиции (упрощенно).
    Если нет данных — пропускаем (True).
    """
    try:
        max_exposure = Decimal(str(getattr(cfg, "MAX_EXPOSURE", "10")))
        exposure = Decimal(str(features.get("exposure", "0")))
        if exposure > max_exposure:
            return False, f"exposure_limit:{exposure}>{max_exposure}"
    except Exception:
        pass
    return _ok()


def check_seq_losses(features: Dict[str, Any], cfg) -> Tuple[bool, str | None]:
    """
    Ограничение на последовательные убыточные сделки (stub-friendly).
    """
    try:
        max_seq = int(getattr(cfg, "MAX_SEQ_LOSSES", 5))
        seq = int(features.get("seq_losses", 0))
        if seq > max_seq:
            return False, f"seq_losses_limit:{seq}>{max_seq}"
    except Exception:
        pass
    return _ok()


def check_hours(features: Dict[str, Any], cfg) -> Tuple[bool, str | None]:
    """
    Простой фильтр по торговым часам (stub). Если отключено — ок.
    """
    enabled = bool(getattr(cfg, "HOURS_FILTER_ENABLED", False))
    if not enabled:
        return _ok()
    # ожидаем, что features содержит поле "hour" в UTC (0..23)
    try:
        hour = int(features.get("hour", 12))
        allowed = getattr(cfg, "HOURS_ALLOWED", list(range(0, 24)))
        if hour not in allowed:
            return False, f"forbidden_hour:{hour}"
    except Exception:
        pass
    return _ok()


def check_spread(features: Dict[str, Any], cfg) -> Tuple[bool, str | None]:
    """
    Проверка спрэда (если в features есть 'spread_pct').
    """
    try:
        limit = float(getattr(cfg, "MAX_SPREAD_PCT", 0.5))
        spread = float(features.get("spread_pct", 0.0))
        if spread > limit:
            return False, f"spread_too_wide:{spread}>{limit}"
    except Exception:
        pass
    return _ok()
