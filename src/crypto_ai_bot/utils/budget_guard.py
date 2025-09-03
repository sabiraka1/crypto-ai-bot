from __future__ import annotations

from typing import Any, Dict, Optional

from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig


def check(
    storage: Any,
    symbol: str,
    settings: Any,
    *,
    risk_manager: Optional[RiskManager] = None,
) -> Optional[Dict[str, str]]:
    """
    Тонкая обёртка над RiskManager: никакой собственной логики.
    Возвращает dict-описание превышения лимита или None (если можно торговать).
    """
    rm = risk_manager or RiskManager(cfg=RiskConfig.from_settings(settings))
    ok, reason, extra = rm.check(symbol=symbol, storage=storage)
    if ok:
        return None

    out: Dict[str, str] = {"type": (extra or {}).get("type", "risk"), "reason": (reason or "blocked")}
    for k, v in (extra or {}).items():
        if v is not None:
            out[k] = str(v)
    return out
