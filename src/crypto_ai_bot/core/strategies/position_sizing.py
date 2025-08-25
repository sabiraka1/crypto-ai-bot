from __future__ import annotations
from typing import Any

def fixed_amount(cfg: Any) -> float:
    """
    Фиксированное количество из настроек.
    В будущем сюда можно добавить риск-процент от equity / волатильностной таргетинг.
    """
    amt = float(getattr(cfg, "FIXED_AMOUNT", 0.001) or 0.001)
    return max(amt, 0.0)
