# src/crypto_ai_bot/core/risk/manager.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Tuple


def _get(d: Dict[str, Any], *path, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def check(features: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """
    Агрегатор риск-правил.
    Ожидаемые (необязательные) поля в features:
      features["market"]["spread_pct"]          float
      features["stats"]["daily_drawdown_pct"]   float
      features["stats"]["seq_losses"]           int
      features["positions"]["exposure_quote"]   Decimal|float
    Отсутствующие поля трактуем как «нет блокирующего сигнала».
    """
    # 1) Spread (если подан)
    spread = _get(features, "market", "spread_pct")
    max_spread = getattr(cfg, "MAX_SPREAD_PCT", None)
    if max_spread is not None and spread is not None:
        try:
            if float(spread) > float(max_spread):
                return False, "spread"
        except Exception:
            pass

    # 2) Дневной drawdown
    dd = _get(features, "stats", "daily_drawdown_pct")
    if dd is not None:
        try:
            if float(dd) > float(getattr(cfg, "MAX_DRAWDOWN_PCT", 100.0)):
                return False, "drawdown"
        except Exception:
            pass

    # 3) Последовательные лоссы
    seq = _get(features, "stats", "seq_losses")
    if seq is not None:
        try:
            if int(seq) > int(getattr(cfg, "MAX_SEQ_LOSSES", 999999)):
                return False, "seq_losses"
        except Exception:
            pass

    # 4) Общая экспозиция (в котир. валюте)
    exposure = _get(features, "positions", "exposure_quote")
    if exposure is not None:
        try:
            exp = float(exposure) if not isinstance(exposure, Decimal) else float(exposure)
            if exp > float(getattr(cfg, "MAX_EXPOSURE_QUOTE", 1e18)):
                return False, "exposure"
        except Exception:
            pass

    return True, "ok"
