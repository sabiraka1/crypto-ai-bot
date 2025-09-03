from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class DailyLossConfig:
    limit_quote: Decimal = Decimal("0")  # 0 = РІС‹РєР»СЋС‡РµРЅРѕ


class DailyLossRule:
    def __init__(self, cfg: DailyLossConfig) -> None:
        self.cfg = cfg

    def _pnl_today(self, trades_repo: Any, symbol: str) -> Decimal | None:
        # Р±С‹СЃС‚СЂС‹Рµ РїСѓС‚Рё
        for name in ("today_realized_pnl_quote", "pnl_today_quote", "realized_pnl_today"):
            if hasattr(trades_repo, name):
                try:
                    return Decimal(str(getattr(trades_repo, name)(symbol)))
                except Exception:
                    pass
        # РёРЅР°С‡Рµ РЅРµ Р·РЅР°РµРј, РєР°Рє РїРѕСЃС‡РёС‚Р°С‚СЊ С‡РµСЃС‚РЅРѕ вЂ” РїСЂРѕРїСѓСЃРєР°РµРј
        return None

    def check(self, *, symbol: str, trades_repo: Any) -> tuple[bool, str, dict]:
        lim = self.cfg.limit_quote
        if lim <= 0:
            return True, "disabled", {}
        val = self._pnl_today(trades_repo, symbol)
        if val is None:
            return True, "no_pnl_data", {}
        # Р»РёРјРёС‚ РЅР° РЈР‘Р«РўРћРљ: РµСЃР»Рё pnl <= -limit -> Р±Р»РѕРє
        if val <= (Decimal("0") - lim):
            return False, "daily_loss_cap", {"pnl_today": str(val), "limit": str(lim)}
        return True, "ok", {}
