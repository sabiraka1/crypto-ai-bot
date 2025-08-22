from __future__ import annotations

import inspect
from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Any, Dict, Optional

import ccxt  # type: ignore

from .base import IBroker, TickerDTO, OrderDTO, BalanceDTO
from ..brokers.symbols import parse_symbol
from ...utils.logging import get_logger
from ...utils.time import now_ms
from ...utils.exceptions import BrokerError, ValidationError, TransientError

getcontext().prec = 28


@dataclass
class _MarketInfo:
    amount_decimals: int
    price_decimals: int
    min_amount: Optional[Decimal]
    min_cost: Optional[Decimal]


def _to_decimal(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _quantize_down(val: Decimal, decimals: int) -> Decimal:
    """Округление вниз к шагу 10^-decimals."""
    if decimals < 0:
        return val
    step = Decimal(1).scaleb(-decimals)  # 10^-decimals
    return (val // step) * step


class CcxtExchange(IBroker):
    """
    Реализация брокера через ccxt для live-режима.

    BUY — по QUOTE-сумме: считаем base по ask с учётом precision/limits.
    SELL — по BASE-сумме: округляем по amount precision.
    """

    def __init__(
        self,
        *,
        exchange: str,
        api_key: str = "",
        api_secret: str = "",
        enable_rate_limit: bool = True,
        timeout_ms: int = 20000,
    ) -> None:
        self._log = get_logger("broker.ccxt")
        klass = getattr(ccxt, exchange)
        self._client = klass(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": enable_rate_limit,
                "timeout": timeout_ms,
            }
        )
        self._markets_loaded = False

    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        try:
            t = await self._call(self._client.fetch_ticker, symbol)
            return TickerDTO(
                symbol=symbol,
                last=float(t.get("last") or t.get("close") or 0.0),
                bid=float(t.get("bid") or t.get("last") or 0.0),
                ask=float(t.get("ask") or t.get("last") or 0.0),
                timestamp=int(t.get("timestamp") or now_ms()),
            )
        except ccxt.NetworkError as e:
            raise TransientError(str(e)) from e
        except ccxt.ExchangeError as e:
            raise BrokerError(str(e)) from e

    async def fetch_balance(self) -> BalanceDTO:
        try:
            b = await self._call(self._client.fetch_balance)
            free: Dict[str, float] = {k: float(v) for k, v in (b.get("free") or {}).items()}
            total: Dict[str, float] = {k: float(v) for k, v in (b.get("total") or {}).items()}
            return BalanceDTO(free=free, total=total)
        except ccxt.NetworkError as e:
            raise TransientError(str(e)) from e
        except ccxt.ExchangeError as e:
            raise BrokerError(str(e)) from e

    async def create_market_buy_quote(
        self,
        symbol: str,
        quote_amount: float,
        *,
        client_order_id: Optional[str] = None,
    ) -> OrderDTO:
        if quote_amount <= 0:
            raise ValidationError("quote_amount must be > 0")
        mkt = await self._market_info(symbol)
        t = await self.fetch_ticker(symbol)
        ask = _to_decimal(t.ask or t.last or 0)
        if ask <= 0:
            raise BrokerError("no ask price")

        quote = _to_decimal(quote_amount)
        base_raw = quote / ask
        base = _quantize_down(base_raw, mkt.amount_decimals)

        # лимиты
        if mkt.min_amount and base < mkt.min_amount:
            raise ValidationError(f"amount too small (min {mkt.min_amount})")
        if mkt.min_cost and quote < mkt.min_cost:
            raise ValidationError(f"cost too small (min {mkt.min_cost})")

        try:
            params: Dict[str, Any] = {}
            if client_order_id:
                params["clientOrderId"] = client_order_id
            await self._call(self._client.create_order, symbol, "market", "buy", float(base), None, params)
            return self._to_order_dto(symbol, "buy", float(base), t, client_order_id=client_order_id)
        except ccxt.RequestTimeout as e:
            raise TransientError(str(e)) from e
        except ccxt.DDoSProtection as e:
            raise TransientError(str(e)) from e
        except ccxt.InvalidOrder as e:
            raise ValidationError(str(e)) from e
        except ccxt.NetworkError as e:
            raise TransientError(str(e)) from e
        except ccxt.ExchangeError as e:
            raise BrokerError(str(e)) from e

    async def create_market_sell_base(
        self,
        symbol: str,
        base_amount: float,
        *,
        client_order_id: Optional[str] = None,
    ) -> OrderDTO:
        if base_amount <= 0:
            raise ValidationError("base_amount must be > 0")
        mkt = await self._market_info(symbol)
        base = _quantize_down(_to_decimal(base_amount), mkt.amount_decimals)
        if mkt.min_amount and base < mkt.min_amount:
            raise ValidationError(f"amount too small (min {mkt.min_amount})")

        t = await self.fetch_ticker(symbol)
        try:
            params: Dict[str, Any] = {}
            if client_order_id:
                params["clientOrderId"] = client_order_id
            await self._call(self._client.create_order, symbol, "market", "sell", float(base), None, params)
            return self._to_order_dto(symbol, "sell", float(base), t, client_order_id=client_order_id)
        except ccxt.RequestTimeout as e:
            raise TransientError(str(e)) from e
        except ccxt.DDoSProtection as e:
            raise TransientError(str(e)) from e
        except ccxt.InvalidOrder as e:
            raise ValidationError(str(e)) from e
        except ccxt.NetworkError as e:
            raise TransientError(str(e)) from e
        except ccxt.ExchangeError as e:
            raise BrokerError(str(e)) from e

    # --- helpers ---
    async def _call(self, func, *args, **kwargs):
        """Вызывает sync/async функции ccxt корректно (без двойного вызова)."""
        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        loop = __import__("asyncio").get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def _market_info(self, symbol: str) -> _MarketInfo:
        if not self._markets_loaded:
            await self._call(self._client.load_markets)
            self._markets_loaded = True
        m = self._client.market(symbol)
        prec = m.get("precision") or {}
        limits = m.get("limits") or {}
        amount_decimals = int(prec.get("amount", 8) or 8)
        price_decimals = int(prec.get("price", 8) or 8)
        min_amount = limits.get("amount", {}).get("min") if limits.get("amount") else None
        min_cost = limits.get("cost", {}).get("min") if limits.get("cost") else None
        return _MarketInfo(
            amount_decimals=amount_decimals,
            price_decimals=price_decimals,
            min_amount=_to_decimal(min_amount) if min_amount else None,
            min_cost=_to_decimal(min_cost) if min_cost else None,
        )

    def _to_order_dto(
        self,
        symbol: str,
        side: str,
        amount: float,
        t: TickerDTO,
        client_order_id: Optional[str] = None,
    ) -> OrderDTO:
        # для BUY берём ask (или last), для SELL — bid (или last)
        px = float((t.ask or t.last) if side == "buy" else (t.bid or t.last) or 0.0)
        return OrderDTO(
            id="",
            client_order_id=client_order_id or "",
            symbol=symbol,
            side=side,
            amount=float(amount),
            price=px,
            cost=float(amount) * px,
            status="closed",
            filled=float(amount),
            timestamp=now_ms(),
        )
