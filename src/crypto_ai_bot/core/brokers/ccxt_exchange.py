## `ccxt_exchange.py`
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Optional
from ...utils.time import now_ms
from ...utils.exceptions import BrokerError, TransientError, ValidationError
from ...utils.retry import retry_async
from ...utils.circuit_breaker import CircuitBreaker
from ...utils.ids import sanitize_ascii
from .base import IBroker, TickerDTO, BalanceDTO, OrderDTO
from .symbols import to_exchange_symbol, from_exchange_symbol, parse_symbol
try:
    import ccxt.async_support as ccxt  # type: ignore
except Exception as e:  # pragma: no cover
    ccxt = None  # type: ignore
@dataclass
class CcxtExchange(IBroker):
    exchange: str = "gateio"
    api_key: str = ""
    api_secret: str = ""
    enable_rate_limit: bool = True
    timeout_ms: int = 20_000
    _client: Any = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _breaker: CircuitBreaker = field(default_factory=CircuitBreaker, init=False)
    async def _ensure_client(self):
        if self._client is not None:
            return
        if ccxt is None:
            raise BrokerError("ccxt not installed")
        ex = (self.exchange or "gateio").lower()
        if not hasattr(ccxt, ex):
            raise BrokerError(f"Unsupported exchange: {ex}")
        klass = getattr(ccxt, ex)
        self._client = klass({
            "apiKey": self.api_key or None,
            "secret": self.api_secret or None,
            "enableRateLimit": self.enable_rate_limit,
            "timeout": self.timeout_ms,
        })
    async def _call(self, coro_factory):
        @retry_async(attempts=5, backoff_base=0.25, backoff_factor=2.0)
        async def _run():
            try:
                await self._ensure_client()
                return await coro_factory()
            except ccxt.RequestTimeout as e:  # type: ignore[attr-defined]
                raise TransientError(str(e))
            except ccxt.NetworkError as e:  # type: ignore[attr-defined]
                raise TransientError(str(e))
            except ccxt.DDoSProtection as e:  # type: ignore[attr-defined]
                raise TransientError(str(e))
            except ccxt.ExchangeNotAvailable as e:  # type: ignore[attr-defined]
                raise TransientError(str(e))
            except Exception as e:
                raise BrokerError(str(e))
        return await _run()
    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        p = parse_symbol(symbol)
        ex_sym = to_exchange_symbol(self.exchange, symbol)
        data = await self._call(lambda: self._client.fetch_ticker(ex_sym))
        last = Decimal(str(data.get("last") or data.get("close") or 0))
        bid = Decimal(str(data.get("bid") or last))
        ask = Decimal(str(data.get("ask") or last))
        ts = int(data.get("timestamp") or now_ms())
        return TickerDTO(symbol=symbol, last=last, bid=bid, ask=ask, timestamp=ts)
    async def fetch_balance(self) -> BalanceDTO:
        data = await self._call(lambda: self._client.fetch_balance())
        free = {k: Decimal(str(v)) for k, v in (data.get("free") or {}).items()}
        used = {k: Decimal(str(v)) for k, v in (data.get("used") or {}).items()}
        total = {k: Decimal(str(v)) for k, v in (data.get("total") or {}).items()}
        return BalanceDTO(free=free, used=used, total=total, timestamp=now_ms())
    async def create_market_buy_quote(self, symbol: str, quote_amount: Decimal, *, client_order_id: str) -> OrderDTO:
        if quote_amount <= 0:
            raise ValidationError("quote_amount must be > 0")
        p = await self.fetch_ticker(symbol)
        ex_sym = to_exchange_symbol(self.exchange, symbol)
        base_amount = (quote_amount / (p.ask if p.ask > 0 else p.last))
        params: Dict[str, Any] = {}
        if client_order_id:
            params["text"] = sanitize_ascii(client_order_id)
        data = await self._call(lambda: self._client.create_order(ex_sym, "market", "buy", float(base_amount), None, params))
        return self._to_order_dto(symbol, "buy", base_amount, quote_amount, client_order_id, data)
    async def create_market_sell_base(self, symbol: str, base_amount: Decimal, *, client_order_id: str) -> OrderDTO:
        if base_amount <= 0:
            raise ValidationError("base_amount must be > 0")
        ex_sym = to_exchange_symbol(self.exchange, symbol)
        params: Dict[str, Any] = {}
        if client_order_id:
            params["text"] = sanitize_ascii(client_order_id)
        data = await self._call(lambda: self._client.create_order(ex_sym, "market", "sell", float(base_amount), None, params))
        p = await self.fetch_ticker(symbol)
        quote_proceeds = base_amount * (p.bid if p.bid > 0 else p.last)
        return self._to_order_dto(symbol, "sell", base_amount, quote_proceeds, client_order_id, data)
    def _to_order_dto(self, symbol: str, side: str, base_amount: Decimal, quote_value: Decimal, client_oid: str, data: Dict[str, Any]) -> OrderDTO:
        oid = str(data.get("id") or data.get("orderId") or data.get("info", {}).get("id") or "")
        status = str(data.get("status") or data.get("info", {}).get("status") or "closed").lower()
        filled = Decimal(str(data.get("filled") or base_amount))
        price = Decimal(str(data.get("average") or data.get("price") or 0))
        if price <= 0:
            try:
                price = (quote_value / base_amount) if base_amount > 0 else Decimal("0")
            except Exception:
                price = Decimal("0")
        ts = int(data.get("timestamp") or now_ms())
        return OrderDTO(
            id=oid or "",
            client_order_id=client_oid,
            symbol=symbol,
            side=side,
            amount=base_amount,
            status=status if status in {"open", "closed", "failed"} else "closed",
            filled=filled,
            price=price,
            cost=quote_value,
            timestamp=ts,
        )
    async def close(self):
        try:
            if self._client is not None:
                await self._client.close()
        except Exception:
            pass
        finally:
            self._client = None