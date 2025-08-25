from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional

try:
    import ccxt.async_support as ccxt  # type: ignore
except Exception:  # ccxt может отсутствовать в окружении тестов — не критично
    ccxt = None  # type: ignore

from .base import IBroker, TickerDTO, OrderDTO, BalanceDTO
from .symbols import parse_symbol, to_exchange_symbol
from ...utils.time import now_ms
from ...utils.logging import get_logger
from ...utils.exceptions import ValidationError, TransientError, BrokerError


_log = get_logger("brokers.ccxt")


@dataclass(frozen=True)
class MarketInfo:
    price_precision: int
    amount_precision: int
    min_quote: Optional[Decimal] = None
    min_base: Optional[Decimal] = None


class CcxtBroker(IBroker):
    """
    Лёгкая CCXT-обёртка, рассчитанная на:
      * корректную семантику buy_quote / sell_base,
      * округление по precision,
      * проверку минимальных лимитов,
      * работу в тестах без реального соединения (если ccxt недоступен).
    """

    def __init__(
        self,
        *,
        exchange_id: str,
        api_key: str = "",
        api_secret: str = "",
        enable_rate_limit: bool = True,
    ) -> None:
        self._ex_id = exchange_id
        self._api_key = api_key
        self._api_secret = api_secret
        self._enable_rl = enable_rate_limit
        self._ex = None
        self._markets: Dict[str, MarketInfo] = {}

    # ---------- lifecycle ----------

    async def _ensure_client(self) -> None:
        if self._ex is not None or ccxt is None:
            return
        ex_cls = getattr(ccxt, self._ex_id, None)
        if ex_cls is None:
            raise BrokerError(f"ccxt exchange '{self._ex_id}' is not available")
        self._ex = ex_cls({"enableRateLimit": self._enable_rl})
        if self._api_key and self._api_secret:
            self._ex.apiKey = self._api_key
            self._ex.secret = self._api_secret
        try:
            await self._ex.load_markets()
        except Exception as exc:
            raise TransientError(str(exc))
        # построим карту precision (best-effort)
        for sym, m in getattr(self._ex, "markets", {}).items():
            try:
                p = int(m.get("precision", {}).get("price", 8))
                a = int(m.get("precision", {}).get("amount", 8))
                min_q = None
                min_b = None
                limits = m.get("limits", {})
                if "cost" in limits and "min" in limits["cost"]:
                    min_q = Decimal(str(limits["cost"]["min"]))
                if "amount" in limits and "min" in limits["amount"]:
                    min_b = Decimal(str(limits["amount"]["min"]))
                self._markets[sym] = MarketInfo(p, a, min_q, min_b)
            except Exception:
                continue

    async def close(self) -> None:
        try:
            if self._ex is not None:
                await self._ex.close()
        finally:
            self._ex = None

    # ---------- helpers ----------

    def _mkt(self, ex_symbol: str) -> MarketInfo:
        # Если неизвестен — консервативные дефолты
        return self._markets.get(ex_symbol, MarketInfo(price_precision=8, amount_precision=8))

    @staticmethod
    def _q(value: Decimal, prec: int) -> Decimal:
        # округление вниз (биржи не любят лишние знаки)
        q = Decimal(10) ** (-prec)
        return (value // q) * q

    def _to_order_dto(self, symbol: str, side: str, o: dict) -> OrderDTO:
        """Конвертер ccxt-ордера в OrderDTO с полным заполнением всех полей."""
        filled = Decimal(str(o.get("filled") or "0"))
        amount = Decimal(str(o.get("amount") or filled))
        remaining = Decimal(str(o.get("remaining") or (amount - filled)))
        
        # Обработка комиссии
        fee_cost = None
        fee_ccy = None
        fee = o.get("fee")
        if isinstance(fee, dict):
            fee_cost = Decimal(str(fee.get("cost") or "0"))
            fee_ccy = fee.get("currency")
        
        # Цена и стоимость
        price = o.get("average") or o.get("price")
        price = None if price is None else Decimal(str(price))
        cost = o.get("cost")
        cost = None if cost is None else Decimal(str(cost))
        
        # Определение статуса
        status = str(o.get("status") or "open")
        if status == "open" and filled > 0 and remaining > 0:
            status = "partial"
        
        return OrderDTO(
            id=str(o.get("id") or ""),
            client_order_id=str(o.get("clientOrderId") or ""),
            symbol=symbol,
            side=side,
            amount=amount,
            filled=filled,
            status=status,
            timestamp=int(o.get("timestamp") or now_ms()),
            price=price,
            cost=cost,
            remaining=remaining,
            fee=fee_cost,
            fee_currency=fee_ccy,
        )

    # ---------- IBroker ----------

    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        p = parse_symbol(symbol)
        ex_symbol = to_exchange_symbol(self._ex_id, p)  # например, BTC/USDT → BTC/USDT или BTC_USDT
        await self._ensure_client()

        if self._ex is None:
            # режим без реального ccxt (тесты): возвращаем пустой тикер
            return TickerDTO(symbol=symbol, last=Decimal("0"), bid=Decimal("0"), ask=Decimal("0"), timestamp=now_ms())

        try:
            t = await self._ex.fetch_ticker(ex_symbol)
        except Exception as exc:
            raise TransientError(str(exc))

        last = Decimal(str(t.get("last") or 0))
        bid = Decimal(str(t.get("bid") or last or 0))
        ask = Decimal(str(t.get("ask") or last or 0))
        return TickerDTO(symbol=symbol, last=last, bid=bid, ask=ask, timestamp=now_ms())

    async def fetch_balance(self) -> BalanceDTO:
        await self._ensure_client()
        if self._ex is None:
            return BalanceDTO(total={}, free={}, used={}, timestamp=now_ms())

        try:
            b = await self._ex.fetch_balance()
        except Exception as exc:
            raise TransientError(str(exc))

        # стандартизируем (Decimal)
        def _as_dec_map(obj: Dict[str, Any]) -> Dict[str, Decimal]:
            out: Dict[str, Decimal] = {}
            for k, v in obj.items():
                try:
                    out[str(k)] = Decimal(str(v))
                except Exception:
                    continue
            return out

        ts = int(b.get("timestamp") or now_ms())
        return BalanceDTO(total=_as_dec_map(b.get("total", {})),
                          free=_as_dec_map(b.get("free", {})),
                          used=_as_dec_map(b.get("used", {})),
                          timestamp=ts)

    async def create_market_buy_quote(self, symbol: str, quote_amount: Decimal, client_order_id: Optional[str] = None) -> OrderDTO:
        """
        Семантика: купить на сумму quote_amount котируемой валюты.
        Пример: BTC/USDT с quote_amount = 100 → рассчитать base_amount по ask.
        """
        if quote_amount <= 0:
            raise ValidationError("quote_amount must be > 0")

        p = parse_symbol(symbol)
        ex_symbol = to_exchange_symbol(self._ex_id, p)
        await self._ensure_client()

        # получим тикер и precision
        t = await self.fetch_ticker(symbol)
        mkt = self._mkt(ex_symbol)

        if t.ask <= 0:
            raise TransientError("no valid ask price")

        # рассчитать базовое количество по ask и округлить вниз под amount precision
        raw_base = (quote_amount / t.ask)
        base_amt = self._q(raw_base, mkt.amount_precision)

        # проверить минимальные лимиты (по base и по quote, если известны)
        if mkt.min_base and base_amt < mkt.min_base:
            raise ValidationError("calculated base amount is too small after rounding")
        if mkt.min_quote and quote_amount < mkt.min_quote:
            raise ValidationError("quote amount below exchange minimum")

        # если клиент подключен — делаем реальный ордер
        if self._ex is not None:
            try:
                params = {}
                if client_order_id:
                    params["clientOrderId"] = client_order_id
                o = await self._ex.create_order(ex_symbol, "market", "buy", float(base_amt), None, params)
                return self._to_order_dto(symbol, "buy", o)
            except Exception as exc:
                raise TransientError(str(exc))
        else:
            # симуляция (тесты): считаем что исполнилось полностью
            return OrderDTO(
                id=client_order_id or f"sim-{now_ms()}",
                client_order_id=client_order_id or f"sim-{now_ms()}",
                symbol=symbol,
                side="buy",
                amount=base_amt,
                status="closed",
                filled=base_amt,
                timestamp=now_ms(),
                remaining=Decimal("0"),
                price=t.ask,
                cost=quote_amount,
            )

    async def create_market_sell_base(self, symbol: str, base_amount: Decimal, client_order_id: Optional[str] = None) -> OrderDTO:
        """
        Семантика: продать ровно base_amount базовой валюты.
        Пример: BTC/USDT с base_amount = 0.001 → округлить по precision, проверить минимум.
        """
        if base_amount <= 0:
            raise ValidationError("base_amount must be > 0")

        p = parse_symbol(symbol)
        ex_symbol = to_exchange_symbol(self._ex_id, p)
        await self._ensure_client()

        mkt = self._mkt(ex_symbol)
        amt = self._q(base_amount, mkt.amount_precision)

        if mkt.min_base and amt < mkt.min_base:
            raise ValidationError("amount_base too small after rounding")

        if self._ex is not None:
            try:
                params = {}
                if client_order_id:
                    params["clientOrderId"] = client_order_id
                o = await self._ex.create_order(ex_symbol, "market", "sell", float(amt), None, params)
                return self._to_order_dto(symbol, "sell", o)
            except Exception as exc:
                raise TransientError(str(exc))
        else:
            # симуляция (тесты): получаем bid для расчета
            t = await self.fetch_ticker(symbol)
            return OrderDTO(
                id=client_order_id or f"sim-{now_ms()}",
                client_order_id=client_order_id or f"sim-{now_ms()}",
                symbol=symbol,
                side="sell",
                amount=amt,
                status="closed",
                filled=amt,
                timestamp=now_ms(),
                remaining=Decimal("0"),
                price=t.bid if t.bid > 0 else t.last,
                cost=amt * (t.bid if t.bid > 0 else t.last),
            )