## `backtest_exchange.py`
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from typing import Callable, Dict, Optional
from ...utils.time import now_ms
from ...utils.exceptions import ValidationError, BrokerError
from .base import IBroker, TickerDTO, BalanceDTO, OrderDTO
from .symbols import parse_symbol
@dataclass
class BacktestExchange(IBroker):
    """Простой in-memory брокер для paper/backtest режимов.
    Параметры:
      balances: стартовые балансы по валютам, например {"USDT": 10000}
      fee_rate: комиссия как доля (например, Decimal('0.001') = 0.1%)
      spread: доля спреда вокруг last (по умолчанию 0.02% суммарно)
      price_feed: функция без аргументов, возвращающая текущую цену last для символа
    """
    symbol: str
    balances: Dict[str, Decimal]
    fee_rate: Decimal = Decimal("0.001")
    spread: Decimal = Decimal("0.0002")
    price_feed: Optional[Callable[[], Decimal]] = None
    _id_seq: int = field(default=1, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    def _get_price(self) -> Decimal:
        if not self.price_feed:
            raise BrokerError("price_feed is not configured for BacktestExchange")
        p = Decimal(self.price_feed())
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
    async def fetch_balance(self) -> BalanceDTO:
        ts = now_ms()
        free = {k: Decimal(v) for k, v in self.balances.items()}
        used = {k: Decimal("0") for k in self.balances}
        total = {k: free[k] + used[k] for k in self.balances}
        return BalanceDTO(free=free, used=used, total=total, timestamp=ts)
    async def create_market_buy_quote(self, symbol: str, quote_amount: Decimal, *, client_order_id: str) -> OrderDTO:
        p = parse_symbol(symbol)
        base, quote = p.base, p.quote
        if quote_amount <= 0:
            raise ValidationError("quote_amount must be > 0")
        async with self._lock:
            self._ensure_currency(base)
            self._ensure_currency(quote)
            price = self._get_price()
            fee = quote_amount * self.fee_rate
            total_cost = quote_amount + fee
            if self.balances[quote] < total_cost:
                raise BrokerError("insufficient_quote_balance")
            base_amount = (quote_amount / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            self.balances[quote] -= total_cost
            self.balances[base] += base_amount
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
                cost=quote_amount,
                timestamp=now_ms(),
            )
    async def create_market_sell_base(self, symbol: str, base_amount: Decimal, *, client_order_id: str) -> OrderDTO:
        p = parse_symbol(symbol)
        base, quote = p.base, p.quote
        if base_amount <= 0:
            raise ValidationError("base_amount must be > 0")
        async with self._lock:
            self._ensure_currency(base)
            self._ensure_currency(quote)
            if self.balances[base] < base_amount:
                raise BrokerError("insufficient_base_balance")
            price = self._get_price()
            proceeds = (base_amount * price)
            fee = proceeds * self.fee_rate
            net = proceeds - fee
            self.balances[base] -= base_amount
            self.balances[quote] += net
            oid = str(self._id_seq)
            self._id_seq += 1
            return OrderDTO(
                id=oid,
                client_order_id=client_order_id,
                symbol=symbol,
                side="sell",
                amount=base_amount,
                status="closed",
                filled=base_amount,
                price=price,
                cost=net,
                timestamp=now_ms(),
            )
