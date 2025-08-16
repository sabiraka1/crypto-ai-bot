# src/crypto_ai_bot/core/risk/manager.py
from __future__ import annotations

"""
Агрегатор правил риска. Никаких внешних вызовов.
Возвращает (ok: bool, reason: str). Первый «фейл» — причина отказа.
"""

from typing import Any, Dict, List, Tuple

from . import rules


def _bool(cfg: Any, name: str, default: bool = True) -> bool:
    raw = getattr(cfg, name, default)
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in ("1", "true", "yes", "on")


def check(features: Dict[str, Any], cfg: Any) -> Tuple[bool, str]:
    """
    Порядок правил важен: дешёвые/безопасные — раньше.
    Все правила — «мягкие»: если нет данных, возвращают ok/n/a.
    Отключение правил через флаги в Settings:
      - ENABLE_RISK_TIME_SYNC
      - ENABLE_RISK_SPREAD
      - ENABLE_RISK_HOURS
      - ENABLE_RISK_SEQ_LOSSES
      - ENABLE_RISK_MAX_EXPOSURE
      - ENABLE_RISK_DRAWDOWN
    """
    chain: List[Tuple[str, Any]] = []

    if _bool(cfg, "ENABLE_RISK_TIME_SYNC", True):
        chain.append(("time_sync", lambda: rules.check_time_sync(cfg)))

    if _bool(cfg, "ENABLE_RISK_SPREAD", True):
        chain.append(("spread", lambda: rules.check_spread(features, cfg)))

    if _bool(cfg, "ENABLE_RISK_HOURS", True):
        chain.append(("hours", lambda: rules.check_hours(cfg)))

    if _bool(cfg, "ENABLE_RISK_SEQ_LOSSES", True):
        chain.append(("seq_losses", lambda: rules.check_seq_losses(features, cfg)))

    if _bool(cfg, "ENABLE_RISK_MAX_EXPOSURE", True):
        chain.append(("max_exposure", lambda: rules.check_max_exposure(features, cfg)))

    if _bool(cfg, "ENABLE_RISK_DRAWDOWN", True):
        chain.append(("drawdown", lambda: rules.check_drawdown(features, cfg)))

    for name, fn in chain:
        ok, reason = fn()
        if not ok:
            return False, f"{name}:{reason}"

    return True, "ok"
