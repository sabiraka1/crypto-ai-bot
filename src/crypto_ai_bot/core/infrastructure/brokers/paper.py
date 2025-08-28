from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from typing import Callable, Dict, Optional

from .base import IBroker, TickerDTO, BalanceDTO, OrderDTO
from .symbols import parse_symbol
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.exceptions import ValidationError, BrokerError
from crypto_ai_bot.utils.decimal import dec  # ← парсер внешних значений


@dataclass
class PaperBroker(IBroker):
    symbol: str
    balances: Dict[str, Decimal]
    fee_rate: Decimal = Decimal("0.001")
    spread: Decimal = Decimal("0.0002")
    price_feed: Optional[Callable[[], Decimal]] = None

    _id_seq: int = field(default=1, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def _get_price(self) -> Decimal:
        if not self.price_feed:
            raise BrokerError("price_feed is not configured for PaperBroker")
        p = dec(self.price_feed())  # ← dec вместо прямого Decimal(...)
        if p <= 0:
            raise BrokerError("price_feed returned non-positive price")
        return p

    def _ensure_currency(self, ccy: str) -> None:
        if ccy not in self.balances:
            self.balances[ccy] = Decimal("0")

    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        p = parse_symbol(symbol)
        last = self._get_price()
        half = (self.spread / Decimal("2"))
        bid = last * (Decimal("1") - half)
        ask = last * (Decimal("1") + half)
        return TickerDTO(symbol=symbol, last=last, bid=bid, ask=ask, timestamp=now_ms())

    async def fetch_balance(self, symbol: str) -> BalanceDTO:
        p = parse_symbol(symbol)
        self._ensure_currency(p.base)
        self._ensure_currency(p.quote)
        return BalanceDTO(free_quote=self.balances[p.quote], free_base=self.balances[p.base])

    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Decimal, client_order_id: str) -> OrderDTO:
        p = parse_symbol(symbol)
        qa = dec(quote_amount)
        if qa <= 0:
            raise ValidationError("quote_amount must be > 0")
        async with self._lock:
            self._ensure_currency(p.base)
            self._ensure_currency(p.quote)
            price = self._get_price()
            fee = qa * self.fee_rate
            total_cost = qa + fee
            if self.balances[p.quote] < total_cost:
                raise BrokerError("insufficient_quote_balance")
            base_amount = (qa / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            self.balances[p.quote] -= total_cost
            self.balances[p.base] += base_amount
            oid = str(self._id_seq)
            self._id_seq += 1
            return OrderDTO(
                id=oid,
                client_order_id=client_order_id,
                symbol=symbol,
                side="buy",
                amount=base_amount,
                status="closed",
                filled=base_amount,
                price=price,
                cost=qa,
                timestamp=now_ms(),
            )

    async def create_market_sell_base(self, *, symbol: str, base_amount: Decimal, client_order_id: str) -> OrderDTO:
        p = parse_symbol(symbol)
        ba = dec(base_amount)
        if ba <= 0:
            raise ValidationError("base_amount must be > 0")
        async with self._lock:
            self._ensure_currency(p.base)
            self._ensure_currency(p.quote)
            if self.balances[p.base] < ba:
                raise BrokerError("insufficient_base_balance")
            price = self._get_price()
            proceeds = (ba * price)
            fee = proceeds * self.fee_rate
            net = proceeds - fee
            self.balances[p.base] -= ba
            self.balances[p.quote] += net
            oid = str(self._id_seq)
            self._id_seq += 1
            return OrderDTO(
                id=oid,
                client_order_id=client_order_id,
                symbol=symbol,
                side="sell",
                amount=ba,
                status="closed",
                filled=ba,
                price=price,
                cost=net,
                timestamp=now_ms(),
            )
