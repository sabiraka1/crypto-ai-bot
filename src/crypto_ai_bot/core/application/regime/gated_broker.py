from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from crypto_ai_bot.core.application.ports import BrokerPort
from crypto_ai_bot.core.domain.macro.regime_detector import RegimeDetector
from crypto_ai_bot.core.domain.macro.types import Regime
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("regime.gated_broker")


@dataclass(frozen=True)
class _Policy:
    # В режиме risk_off запрещаем новые входы (покупки). Продажи/закрытия всегда разрешены.
    block_new_longs_on_risk_off: bool = True


class GatedBroker(BrokerPort):
    """
    Обёртка над BrokerPort: проверяет макро-режим перед созданием ордера.
    Совместима с твоей сигнатурой:
        GatedBroker(inner=..., regime=<RegimeDetector|None>, allow_sells_when_off=True)
    """
    def __init__(
        self,
        inner: BrokerPort,
        regime: Optional[RegimeDetector] = None,
        allow_sells_when_off: bool = True,
    ) -> None:
        self._inner = inner
        self._regime = regime
        self._policy = _Policy(block_new_longs_on_risk_off=True)
        self._allow_sells = allow_sells_when_off

    # ---------- рыночные данные / прокси ----------
    async def fetch_ticker(self, symbol: str) -> Any:
        return await self._inner.fetch_ticker(symbol)

    async def fetch_balance(self, symbol: str) -> Any:
        return await self._inner.fetch_balance(symbol)

    async def fetch_order(self, *, symbol: str, broker_order_id: str) -> Any:
        return await self._inner.fetch_order(symbol=symbol, broker_order_id=broker_order_id)

    # ---------- торговые операции ----------
    async def create_market_buy_quote(
        self, *, symbol: str, quote_amount: Decimal, client_order_id: str | None = None
    ) -> Any:
        if self._regime and self._policy.block_new_longs_on_risk_off:
            r: Regime = await self._regime.regime()
            if r == "risk_off":
                _log.warning("blocked_buy_by_regime", extra={"symbol": symbol, "regime": r, "quote_amount": str(quote_amount)})
                raise RuntimeError("blocked_by_regime:risk_off")
        return await self._inner.create_market_buy_quote(
            symbol=symbol, quote_amount=quote_amount, client_order_id=client_order_id
        )

    async def create_market_sell_base(
        self, *, symbol: str, base_amount: Decimal, client_order_id: str | None = None
    ) -> Any:
        # Выходы разрешаем всегда (если даже режим risk_off)
        return await self._inner.create_market_sell_base(
            symbol=symbol, base_amount=base_amount, client_order_id=client_order_id
        )
