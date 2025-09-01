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
class GatingPolicy:
    """
    Политика ограничений по макро-режиму.
    Сейчас: в risk_off запрещаем новые long-входы (покупки).
    """
    block_new_longs_on_risk_off: bool = True


class GatedBroker(BrokerPort):
    """
    Декоратор для BrokerPort: перед созданием ордера проверяет RegimeDetector.
    - Покупки (входы) блокируются в режиме risk_off (если включено политикой).
    - Продажи и закрытия разрешены всегда.
    Если detector=None — полное прозрачное проксирование.
    """

    def __init__(self, inner: BrokerPort, detector: Optional[RegimeDetector], policy: Optional[GatingPolicy] = None) -> None:
        self._inner = inner
        self._detector = detector
        self._policy = policy or GatingPolicy()

    # -------- рыночные данные / прокси --------
    async def fetch_ticker(self, symbol: str) -> Any:
        return await self._inner.fetch_ticker(symbol)

    async def fetch_balance(self, symbol: str) -> Any:
        return await self._inner.fetch_balance(symbol)

    async def fetch_order(self, *, symbol: str, broker_order_id: str) -> Any:
        return await self._inner.fetch_order(symbol=symbol, broker_order_id=broker_order_id)

    # -------- торговля --------
    async def create_market_buy_quote(
        self, *, symbol: str, quote_amount: Decimal, client_order_id: str | None = None
    ) -> Any:
        if self._detector and self._policy.block_new_longs_on_risk_off:
            regime: Regime = await self._detector.regime()
            if regime == "risk_off":
                _log.warning("blocked_buy_by_regime", extra={"symbol": symbol, "regime": regime, "qa": str(quote_amount)})
                raise RuntimeError("blocked_by_regime:risk_off")
        return await self._inner.create_market_buy_quote(symbol=symbol, quote_amount=quote_amount, client_order_id=client_order_id)

    async def create_market_sell_base(
        self, *, symbol: str, base_amount: Decimal, client_order_id: str | None = None
    ) -> Any:
        # Продажи разрешаем всегда (выходы безопасности)
        return await self._inner.create_market_sell_base(symbol=symbol, base_amount=base_amount, client_order_id=client_order_id)
