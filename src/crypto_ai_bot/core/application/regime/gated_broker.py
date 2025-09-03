from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.application.ports import BrokerPort
from crypto_ai_bot.core.domain.macro.regime_detector import RegimeDetector
from crypto_ai_bot.core.domain.macro.types import Regime
from crypto_ai_bot.utils.logging import get_logger


_log = get_logger("regime.gated_broker")


@dataclass(frozen=True)
class _Policy:
    # Ğ’ Ñ€ĞµĞ¶Ğ¸Ğ¼Ğµ risk_off Ğ·Ğ°Ğ¿Ñ€ĞµÑ‰Ğ°ĞµĞ¼ Ğ½Ğ¾Ğ²Ñ‹Ğµ Ğ²Ñ…Ğ¾Ğ´Ñ‹ (Ğ¿Ğ¾ĞºÑƒĞ¿ĞºĞ¸). ĞŸÑ€Ğ¾Ğ´Ğ°Ğ¶Ğ¸/Ğ·Ğ°ĞºÑ€Ñ‹Ñ‚Ğ¸Ñ Ğ²ÑĞµĞ³Ğ´Ğ° Ñ€Ğ°Ğ·Ñ€ĞµÑˆĞµĞ½Ñ‹.
    block_new_longs_on_risk_off: bool = True


class GatedBroker(BrokerPort):
    """
    ĞĞ±Ñ‘Ñ€Ñ‚ĞºĞ° Ğ½Ğ°Ğ´ BrokerPort: Ğ¿Ñ€Ğ¾Ğ²ĞµÑ€ÑĞµÑ‚ Ğ¼Ğ°ĞºÑ€Ğ¾-Ñ€ĞµĞ¶Ğ¸Ğ¼ Ğ¿ĞµÑ€ĞµĞ´ ÑĞ¾Ğ·Ğ´Ğ°Ğ½Ğ¸ĞµĞ¼ Ğ¾Ñ€Ğ´ĞµÑ€Ğ°.
    Ğ¡Ğ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ğ° Ñ Ñ‚Ğ²Ğ¾ĞµĞ¹ ÑĞ¸Ğ³Ğ½Ğ°Ñ‚ÑƒÑ€Ğ¾Ğ¹:
        GatedBroker(inner=..., regime=<RegimeDetector|None>, allow_sells_when_off=True)
    """
    def __init__(
        self,
        inner: BrokerPort,
        regime: RegimeDetector | None = None,
        allow_sells_when_off: bool = True,
    ) -> None:
        self._inner = inner
        self._regime = regime
        self._policy = _Policy(block_new_longs_on_risk_off=True)
        self._allow_sells = allow_sells_when_off

    # ---------- Ñ€Ñ‹Ğ½Ğ¾Ñ‡Ğ½Ñ‹Ğµ Ğ´Ğ°Ğ½Ğ½Ñ‹Ğµ / Ğ¿Ñ€Ğ¾ĞºÑĞ¸ ----------
    async def fetch_ticker(self, symbol: str) -> Any:
        return await self._inner.fetch_ticker(symbol)

    async def fetch_balance(self, symbol: str) -> Any:
        return await self._inner.fetch_balance(symbol)

    async def fetch_order(self, *, symbol: str, broker_order_id: str) -> Any:
        return await self._inner.fetch_order(symbol=symbol, broker_order_id=broker_order_id)

    # ---------- Ñ‚Ğ¾Ñ€Ğ³Ğ¾Ğ²Ñ‹Ğµ Ğ¾Ğ¿ĞµÑ€Ğ°Ñ†Ğ¸Ğ¸ ----------
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
        # Ğ’Ñ‹Ñ…Ğ¾Ğ´Ñ‹ Ñ€Ğ°Ğ·Ñ€ĞµÑˆĞ°ĞµĞ¼ Ğ²ÑĞµĞ³Ğ´Ğ° (ĞµÑĞ»Ğ¸ Ğ´Ğ°Ğ¶Ğµ Ñ€ĞµĞ¶Ğ¸Ğ¼ risk_off)
        return await self._inner.create_market_sell_base(
            symbol=symbol, base_amount=base_amount, client_order_id=client_order_id
        )
