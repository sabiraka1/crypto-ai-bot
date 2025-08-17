from __future__ import annotations
from typing import Dict, Any, Tuple

from . import rules

def check(features: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """
    Агрегатор risk-правил. Никаких IO/брокеров/БД — только pure checks.
    Ожидаемые поля (опционально, если нет — правило пропускается):
      features["context"]["bars"]          -> int
      features["context"]["exposure"]      -> Decimal|float|str (в базовых единицах)
      features["context"]["time_drift_ms"] -> int
    Пороговые значения берём из Settings (с дефолтами).
    """
    ctx = features.get("context") or features.get("market") or {}

    # 1) Минимальная история баров
    min_bars = getattr(cfg, "MIN_HISTORY_BARS", 300)
    ok, reason = rules.check_min_history(ctx.get("bars"), min_bars)
    if not ok:
        return False, reason

    # 2) Максимальная экспозиция (в базовых единицах)
    max_units = getattr(cfg, "MAX_EXPOSURE_UNITS", "0")  # "0" == отключено
    ok, reason = rules.check_max_exposure(ctx.get("exposure"), max_units)
    if not ok:
        return False, reason

    # 3) Time drift (доп. слой, основной стоп есть в policy)
    limit_ms = getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000)
    ok, reason = rules.check_time_sync(ctx.get("time_drift_ms"), limit_ms)
    if not ok:
        return False, reason

    return True, "ok"
