# src/crypto_ai_bot/core/risk/manager.py
from __future__ import annotations
from typing import Any, Dict, Tuple

from . import rules


def check(features: Dict[str, Any], cfg) -> Tuple[bool, str]:
    # 1) синхронизация времени
    ok, reason = rules.check_time_sync(cfg)
    if not ok:
        return ok, reason
    # здесь добавляй другие проверки: spread/hours/DD/seq_losses/max_exposure …
    return True, "ok"
