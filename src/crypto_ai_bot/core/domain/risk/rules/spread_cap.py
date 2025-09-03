from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class SpreadCapConfig:
    max_spread_pct: float = 0.0  # 0 = выключено

class SpreadCapRule:
    """
    Проверяем текущий спрэд. Источник даём в виде провайдера:
      provider(symbol) -> float (процент спрэда), либо None.
    Если провайдера нет/ошибка — правило молча пропускается.
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
