from __future__ import annotations

from typing import Dict, Any, Tuple, List

from . import rules


def check(features: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """
    Проверяем набор правил. Возвращаем общий вердикт и свёртку причин.
    """
    context = features.get("context", {}) if isinstance(features, dict) else {}
    bars = context.get("bars")
    drift_ms = context.get("time_drift_ms")

    reasons: List[str] = []

    # 1) рассинхронизация времени
    ok1, r1 = rules.check_time_sync(drift_ms, getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000))
    if not ok1:
        reasons.append(r1)

    # 2) минимальная история
    ok2, r2 = rules.check_min_history(bars, getattr(cfg, "MIN_HISTORY_BARS", 100))
    if not ok2:
        reasons.append(r2)

    if reasons:
        return False, ";".join(reasons)
    return True, "ok"
