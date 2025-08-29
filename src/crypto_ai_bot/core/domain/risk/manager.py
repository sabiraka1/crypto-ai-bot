# src/crypto_ai_bot/core/domain/risk/manager.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from crypto_ai_bot.utils.decimal import dec


@dataclass(frozen=True)
class RiskConfig:
    cooldown_sec: int = 0
    max_spread_pct: Decimal = dec("0.02")          # 2% по умолчанию
    max_position_base: Decimal = dec("0")          # 0 => без лимита
    max_orders_per_hour: int = 0                   # 0 => без лимита
    daily_loss_limit_quote: Decimal = dec("0")     # 0 => без лимита
    max_fee_pct: Decimal = dec("0.005")            # 0.5% по умолчанию
    max_slippage_pct: Decimal = dec("0.01")        # 1% по умолчанию


@dataclass(frozen=True)
class RiskInputs:
    # рынок
    spread_pct: Decimal
    # состояние
    position_base: Decimal
    # история
    recent_orders: int
    pnl_daily_quote: Decimal
    # внутренние состояния/оценки
    cooldown_active: bool
    est_fee_pct: Decimal = dec("0")
    est_slippage_pct: Decimal = dec("0")
    # контекст операции
    side: str = ""  # "buy" | "sell" (для sell ослабляем некоторые запреты)


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self._cfg = config

    def check(self, r: RiskInputs) -> Dict[str, object]:
        """
        Возвращает {"ok": bool, "deny_reasons": List[str]}.
        Логика:
          - Правила «всегда» (для buy и sell): cooldown, дикий спред, частота ордеров.
          - Правила «только для покупок»: дневной лимит убытка, лимит позиции, fee/slippage.
        """
        reasons: List[str] = []

        side = (r.side or "").lower()

        # 1) Всегда-блокирующие
        if r.cooldown_active and self._cfg.cooldown_sec > 0:
            reasons.append("cooldown_active")

        if self._cfg.max_spread_pct and r.spread_pct is not None:
            try:
                if r.spread_pct > self._cfg.max_spread_pct:
                    reasons.append("spread_too_wide")
            except Exception:
                pass

        if self._cfg.max_orders_per_hour and r.recent_orders is not None:
            if r.recent_orders >= int(self._cfg.max_orders_per_hour):
                reasons.append("orders_per_hour_limit")

        # 2) Только для покупок (не мешает закрываться SELL’ом при проблемах)
        if side == "buy":
            if self._cfg.daily_loss_limit_quote and r.pnl_daily_quote is not None:
                # если уже в минусе больше лимита — запрещаем новые покупки
                if r.pnl_daily_quote < (dec("0") - abs(self._cfg.daily_loss_limit_quote)):
                    reasons.append("daily_loss_limit_exceeded")

            if self._cfg.max_position_base and r.position_base is not None:
                # если позиция уже выше лимита — новые покупки запрещены
                if r.position_base >= self._cfg.max_position_base:
                    reasons.append("position_limit_reached")

            # ожидаемые транзакционные издержки
            if self._cfg.max_fee_pct and r.est_fee_pct and r.est_fee_pct > self._cfg.max_fee_pct:
                reasons.append("fee_estimate_too_high")
            if self._cfg.max_slippage_pct and r.est_slippage_pct and r.est_slippage_pct > self._cfg.max_slippage_pct:
                reasons.append("slippage_estimate_too_high")

        ok = len(reasons) == 0
        return {"ok": ok, "deny_reasons": reasons}
