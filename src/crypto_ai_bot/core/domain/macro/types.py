from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Regime = Literal["risk_on", "risk_off", "range"]

@dataclass
class MacroSnapshot:
    dxy_change_pct: float | None = None
    btc_dom_change_pct: float | None = None
    fomc_event_today: bool = False
