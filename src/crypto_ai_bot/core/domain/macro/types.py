# src/crypto_ai_bot/core/domain/macro/types.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Literal

Regime = Literal["risk_on", "range", "risk_off"]

@dataclass(frozen=True)
class MacroSnapshot:
    """Снимок макро-показателей, на основе которых определяем режим рынка."""
    dxy_change_pct: Optional[float] = None     # % изменение за период (например, 24ч)
    btc_dom_change_pct: Optional[float] = None # % изменение доминации BTC
    fomc_event_today: bool = False             # есть ли заседание ФРС (или окно вокруг него)
