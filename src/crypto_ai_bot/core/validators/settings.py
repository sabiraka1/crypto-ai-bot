from __future__ import annotations
from typing import Any, List

def validate_trading_params(s: Any) -> List[str]:
    """
    Мини-валидация торговых параметров:
      - MODE=live -> требуются API_KEY/API_SECRET
      - IDEMPOTENCY_TTL_SEC > 0
      - FIXED_AMOUNT > 0
    """
    errors: List[str] = []

    mode = str(getattr(s, "MODE", "paper")).lower()
    if mode == "live":
        if not getattr(s, "API_KEY", None) or not getattr(s, "API_SECRET", None):
            errors.append("MODE=live requires API_KEY and API_SECRET")

    ttl = int(getattr(s, "IDEMPOTENCY_TTL_SEC", 60) or 60)
    if ttl <= 0:
        errors.append("IDEMPOTENCY_TTL_SEC must be > 0")

    amt = float(getattr(s, "FIXED_AMOUNT", 0.0) or 0.0)
    if amt <= 0:
        errors.append("FIXED_AMOUNT must be > 0")

    return errors
