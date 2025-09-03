from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class SpreadCapConfig:
    max_spread_pct: float = 0.0  # 0 = РІС‹РєР»СЋС‡РµРЅРѕ


class SpreadCapRule:
    """
    РџСЂРѕРІРµСЂСЏРµРј С‚РµРєСѓС‰РёР№ СЃРїСЂСЌРґ. РСЃС‚РѕС‡РЅРёРє РґР°С‘Рј РІ РІРёРґРµ РїСЂРѕРІР°Р№РґРµСЂР°:
      provider(symbol) -> float (РїСЂРѕС†РµРЅС‚ СЃРїСЂСЌРґР°), Р»РёР±Рѕ None.
    Р•СЃР»Рё РїСЂРѕРІР°Р№РґРµСЂР° РЅРµС‚/РѕС€РёР±РєР° вЂ” РїСЂР°РІРёР»Рѕ РјРѕР»С‡Р° РїСЂРѕРїСѓСЃРєР°РµС‚СЃСЏ.
    """

    def __init__(self, cfg: SpreadCapConfig, provider: Callable[[str], float] | None = None) -> None:
        self.cfg = cfg
        self.provider = provider

    def check(self, *, symbol: str) -> tuple[bool, str, dict]:
        if self.cfg.max_spread_pct <= 0:
            return True, "disabled", {}
        if not self.provider:
            return True, "no_provider", {}
        try:
            spread = float(self.provider(symbol))
        except Exception:
            return True, "provider_error", {}
        if spread >= self.cfg.max_spread_pct:
            return False, "spread_cap", {"spread_pct": spread, "limit_pct": self.cfg.max_spread_pct}
        return True, "ok", {}
