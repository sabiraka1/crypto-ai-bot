from __future__ import annotations

from decimal import Decimal
from typing import Dict, Tuple

from crypto_ai_bot.core.risk import rules
from crypto_ai_bot.utils import metrics


def check(features: Dict, cfg) -> Tuple[bool, str]:
    """
    Агрегирует правила риска → вердикт.
    features ожидает поля (если есть):
      features["time"]["drift_ms"] -> int
      features["risk"]["exposure"] -> Decimal
      features["risk"]["loss_streak"] -> int
    cfg ожидает:
      TIME_DRIFT_LIMIT_MS (int), MAX_EXPOSURE (Decimal), MAX_LOSS_STREAK (int)
    Отсутствующие поля пропускаются.
    """
    # 1) time sync
    drift_ms = int(features.get("time", {}).get("drift_ms", 0))
    ok, reason = rules.check_time_sync(drift_ms, int(getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000)))
    if not ok:
        metrics.inc("risk_block_total", {"reason": "time_sync"})
        return False, reason

    # 2) exposure (опционально)
    exposure = features.get("risk", {}).get("exposure", None)
    max_exposure = getattr(cfg, "MAX_EXPOSURE", None)
    if exposure is not None and max_exposure is not None:
        ok, reason = rules.check_max_exposure(Decimal(str(exposure)), Decimal(str(max_exposure)))
        if not ok:
            metrics.inc("risk_block_total", {"reason": "exposure"})
            return False, reason

    # 3) sequential losses (опционально)
    loss_streak = features.get("risk", {}).get("loss_streak", None)
    max_streak = getattr(cfg, "MAX_LOSS_STREAK", None)
    if loss_streak is not None and max_streak is not None:
        ok, reason = rules.check_seq_losses(int(loss_streak), int(max_streak))
        if not ok:
            metrics.inc("risk_block_total", {"reason": "seq_losses"})
            return False, reason

    return True, ""
