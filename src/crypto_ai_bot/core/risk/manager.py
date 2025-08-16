from __future__ import annotations

from typing import Any, Dict, Tuple, List

from crypto_ai_bot.utils import metrics
from . import rules


def check(features: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """
    Единая точка агрегации risk-правил.
    Возвращает (ok, reason). Первый фэйл — останавливаемся.
    Порядок важен: time_sync — самый первый.
    """
    sequence = [
        ("time_sync", lambda: rules.check_time_sync(cfg)),
        # Ниже — оставлены заглушки/пример вызовов. При необходимости включайте.
        # ("hours",      lambda: rules.check_hours(features, cfg)),
        # ("spread",     lambda: rules.check_spread(features, cfg)),
        # ("exposure",   lambda: rules.check_max_exposure(features.get("exposure"), cfg)),
        # ("seq_losses", lambda: rules.check_seq_losses(features.get("seq_losses"), cfg)),
    ]

    for name, fn in sequence:
        res = fn()
        if not res.ok:
            # метрики и понятная причина отказа
            try:
                metrics.inc("risk_verdict_total", {"rule": name, "result": "blocked"})
            except Exception:
                pass
            return False, res.reason

    try:
        metrics.inc("risk_verdict_total", {"rule": "all", "result": "ok"})
    except Exception:
        pass

    return True, "ok"
