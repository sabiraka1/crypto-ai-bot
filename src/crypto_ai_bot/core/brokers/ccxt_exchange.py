from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from .base import IBroker, TickerDTO, OrderDTO, BalanceDTO
from .symbols import parse_symbol
from ...utils.number import to_decimal
from ...utils.logging import get_logger
from ...utils.retry import retry_async
from ...utils.circuit_breaker import CircuitBreaker
from ...utils.exceptions import ValidationError, TransientError

try:
    import ccxt.async_support as ccxt  # type: ignore
except Exception as exc:  # pragma: no cover
    ccxt = None


_log = get_logger("brokers.ccxt")


@dataclass
class _MarketInfo:
    price_precision: int
    amount_precision: int
    min_cost: Optional[Decimal] = None
    min_amount: Optional[Decimal] = None


def _round_amount(x: Decimal, precision: int) -> Decimal:
    if precision < 0:
        return x
    q = Decimal(10) ** (-precision)
    return (x // q) * q


class CcxtBroker(IBroker):
    """
    Лёгкий адаптер поверх CCXT с нормализацией под наши DTO и безопасными конвертациями.
    Вызовы обёрнуты в CircuitBreaker + retry для устойчивости.
    """

    def __init__(
        self,
        *,
        exchange_id: str = "gateio",
        api_key: str = "",
        api_secret: str = "",
        enable_rate_limit: bool = True,
    ) -> None:
        if ccxt is None:  # pragma: no cover
            raise RuntimeError("ccxt is not available")

        cls = getattr(ccxt, exchange_id)
        self._client = cls({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": enable_rate_limit,
        })
        self._breaker = CircuitBreaker(failures_threshold=5, open_timeout_ms=30_000)

    async def _load_markets(self) -> Dict[str, Any]:
        return await self._client.load_markets()

    def _market_info(self, markets: Dict[str, Any], symbol: str) -> _MarketInfo:
        m = markets.get(symbol) or {}
        # CCXT хранит precision как dict {'price': int, 'amount': int}
        pr = int((m.get("precision") or {}).get("price") or 8)
        am = int((m.get("precision") or {}).get("amount") or 8)

        limits = m.get("limits") or {}
        cost_min = to_decimal((limits.get("cost") or {}).get("min"), default=None)
        amt_min = to_decimal((limits.get("amount") or {}).get("min"), default=None)
        return _MarketInfo(price_precision=pr, amount_precision=am, min_cost=cost_min, min_amount=amt_min)

    # ---------- базовые чтения ----------

    @retry_async(attempts=3, retry_on=(TransientError, TimeoutError, ConnectionError))
    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        async def _call():
            t = await self._client.fetch_ticker(symbol)
            return TickerDTO(
                symbol=symbol,
                last=to_decimal(t.get("last")),
                bid=to_decimal(t.get("bid")),
                ask=to_decimal(t.get("ask")),
                timestamp=int(t.get("timestamp") or 0),
            )
        return await self._breaker.run_async(_call)

    @retry_async(attempts=3, retry_on=(TransientError, TimeoutError, ConnectionError))
    async def fetch_balance(self, symbol: str) -> BalanceDTO:
        async def _call():
            ps = parse_symbol(symbol)     # base/quote
            b = await self._client.fetch_balance()

            # CCXT баланс: {'free': {'USDT': 1000, 'BTC': 0.1}, 'total': {...}}
            free = b.get("free") or {}
            total = b.get("total") or {}

            free_quote = to_decimal(free.get(ps.quote, 0))
            free_base  = to_decimal(free.get(ps.base, 0))
            total_quote = to_decimal(total.get(ps.quote), default=None)
            total_base  = to_decimal(total.get(ps.base),  default=None)
            return BalanceDTO(
                free_quote=free_quote,
                free_base=free_base,
                total_quote=total_quote,
                total_base=total_base,
            )
        return await self._breaker.run_async(_call)

    # ---------- торговля ----------

    @retry_async(attempts=3, retry_on=(TransientError, TimeoutError, ConnectionError))
    async def create_market_buy_quote(
        self, *, symbol: str, quote_amount: Decimal, client_order_id: str
    ) -> OrderDTO:
        async def _call():
            markets = await self._load_markets()
            info = self._market_info(markets, symbol)

            if info.min_cost is not None and quote_amount < info.min_cost:
                raise ValidationError("quote_amount below min_cost")

            # CCXT маркет-бай: указываем cost через amount в quote, если биржа поддерживает,
            # иначе переводим в приблизительный base через текущий ask.
            t = await self._client.fetch_ticker(symbol)
            ask = to_decimal(t.get("ask"))
            if ask <= 0:
                raise ValidationError("invalid ask price")

            approx_base = quote_amount / ask
            base_rounded = _round_amount(approx_base, info.amount_precision)
            if info.min_amount is not None and base_rounded < info.min_amount:
                raise ValidationError("calculated base amount is too small after rounding")

            o = await self._client.create_order(
                symbol=symbol,
                type="market",
                side="buy",
                amount=float(base_rounded),     # CCXT принимает float
                params={"clientOrderId": client_order_id},
            )
            return self._to_order_dto(o, symbol)

        return await self._breaker.run_async(_call)

    @retry_async(attempts=3, retry_on=(TransientError, TimeoutError, ConnectionError))
    async def create_market_sell_base(
        self, *, symbol: str, base_amount: Decimal, client_order_id: str
    ) -> OrderDTO:
        async def _call():
            markets = await self._load_markets()
            info = self._market_info(markets, symbol)

            base_rounded = _round_amount(base_amount, info.amount_precision)
            if info.min_amount is not None and base_rounded < info.min_amount:
                raise ValidationError("amount_base too small after rounding")

            o = await self._client.create_order(
                symbol=symbol,
                type="market",
                side="sell",
                amount=float(base_rounded),
                params={"clientOrderId": client_order_id},
            )
            return self._to_order_dto(o, symbol)

        return await self._breaker.run_async(_call)

    # ---------- helpers ----------

    def _to_order_dto(self, raw: Dict[str, Any], symbol: str) -> OrderDTO:
        """
        Унификация CCXT ордера в наш OrderDTO. Поля price/cost/remaining/fee — опциональные.
        """
        filled = to_decimal(raw.get("filled"))
        amount = to_decimal(raw.get("amount"))
        remaining = to_decimal(raw.get("remaining"), default=None)

        fee = None
        fee_currency = None
        fee_raw = raw.get("fee")
        if isinstance(fee_raw, dict):
            fee = to_decimal(fee_raw.get("cost"), default=None)
            fee_currency = fee_raw.get("currency")

        return OrderDTO(
            id=str(raw.get("id") or ""),
            client_order_id=str(raw.get("clientOrderId") or raw.get("client_order_id") or ""),
            symbol=symbol,
            side=str(raw.get("side") or ""),
            amount=amount,
            status=str(raw.get("status") or "open"),
            filled=filled,
            timestamp=int(raw.get("timestamp") or 0),
            price=to_decimal(raw.get("price"), default=None),
            cost=to_decimal(raw.get("cost"), default=None),
            remaining=remaining,
            fee=fee,
            fee_currency=fee_currency,
        )

    # ---------- lifecycle ----------

    async def close(self) -> None:
        try:
            await self._client.close()
        except Exception:
            pass
