from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Any

from crypto_ai_bot.core.application.ports import StoragePort
from crypto_ai_bot.utils.decimal import dec


@dataclass
class RiskManager:
    storage: StoragePort
    # строго необходимые конфиги для бюджета/лимитов
    max_position_base: Decimal = dec("0")   # 0 = без лимита
    max_daily_turnover_quote: Decimal = dec("0")  # 0 = без лимита
    max_daily_orders: int = 0  # 0 = без лимита

    @classmethod
    def from_settings(cls, *, storage: StoragePort, settings: Any) -> "RiskManager":
        return cls(
            storage=storage,
            max_position_base=dec(str(getattr(settings, "RISK_MAX_POSITION_BASE", "0") or "0")),
            max_daily_turnover_quote=dec(str(getattr(settings, "SAFETY_MAX_TURNOVER_QUOTE_PER_DAY", "0") or "0")),
            max_daily_orders=int(getattr(settings, "SAFETY_MAX_ORDERS_PER_DAY", 0) or 0),
        )

    def allow(
        self,
        *,
        symbol: str,
        action: str,
        quote_amount: Optional[Decimal],
        base_amount: Optional[Decimal],
    ) -> tuple[bool, str]:
        """Единые бюджетные проверки: позиция, дневной оборот, число ордеров."""
        act = (action or "").lower()
        if act not in {"buy", "sell"}:
            return False, "invalid_action"

        # лимит по числу ордеров в сутки (UTC)
        if self.max_daily_orders > 0:
            try:
                n = self.storage.trades.count_orders_last_minutes(symbol, 24 * 60)
                if n >= self.max_daily_orders:
                    return False, "day_orders_limit"
            except Exception:
                pass

        # лимит дневного оборота (котируемая)
        if self.max_daily_turnover_quote > 0 and quote_amount and quote_amount > 0:
            try:
                spent = self.storage.trades.daily_turnover_quote(symbol)
                if spent + quote_amount > self.max_daily_turnover_quote:
                    return False, "day_turnover_limit"
            except Exception:
                pass

        # лимит по размеру позиции (только для buy)
        if act == "buy" and self.max_position_base > 0:
            try:
                cur = self.storage.positions.get_base_qty(symbol) or dec("0")
                # оценочно: base прирост ≈ quote_amount / last — эта проверка «мягкая»,
                # точный контроль выполняется в orchestrator/place_order.
                if cur >= self.max_position_base:
                    return False, "position_limit"
            except Exception:
                pass

        return True, "ok"
