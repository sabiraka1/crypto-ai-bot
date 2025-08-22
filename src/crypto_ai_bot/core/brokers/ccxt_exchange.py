# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional

from .base import IBroker, TickerDTO, OrderDTO  # DTO/protocol из твоего фундамента
from .symbols import (
    market_info_from_ccxt,
    round_base_step,
    ensure_min_notional_ok,
)
from ...utils.time import now_ms
from ...utils.logging import get_logger
from ...utils.exceptions import ValidationError, TransientError, BrokerError

_log = get_logger("brokers.ccxt")

try:
    import ccxt  # type: ignore
except Exception as exc:
    ccxt = None
    _import_err = exc
else:
    _import_err = None


def _to_decimal(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


@dataclass
class CcxtBroker(IBroker):
    exchange_id: str
    api_key: str
    api_secret: str
    enable_sandbox: bool = False

    def __post_init__(self) -> None:
        if ccxt is None:
            raise BrokerError(f"ccxt is not installed: {_import_err}")
        cls = getattr(ccxt, self.exchange_id, None)
        if cls is None:
            raise BrokerError(f"Unknown exchange id for ccxt: {self.exchange_id}")
        self._ex = cls({
            "apiKey": self.api_key or None,
            "secret": self.api_secret or None,
            "enableRateLimit": True,
            "options": {},
        })
        if self.enable_sandbox and hasattr(self._ex, "set_sandbox_mode"):
            try:
                self._ex.set_sandbox_mode(True)  # not all exchanges support it
            except Exception:
                pass

    # --- helpers ---
    async def _call(self, fn, *args, **kwargs):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except (ccxt.NetworkError, ccxt.DDoSProtection, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as e:  # type: ignore
            raise TransientError(str(e))
        except ccxt.AuthenticationError as e:  # type: ignore
            raise BrokerError(f"auth_error: {e}")
        except ccxt.ExchangeError as e:  # type: ignore
            raise BrokerError(f"exchange_error: {e}")
        except Exception as e:
            raise BrokerError(str(e))

    # --- IBroker API ---
    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        t = await self._call(self._ex.fetch_ticker, symbol)
        bid = _to_decimal(t.get("bid"))
        ask = _to_decimal(t.get("ask"))
        last = _to_decimal(t.get("last")) if t.get("last") is not None else (bid + ask) / Decimal("2") if (bid and ask) else bid or ask
        return TickerDTO(
            symbol=symbol,
            last=float(last),
            bid=float(bid),
            ask=float(ask),
            timestamp=int(t.get("timestamp") or now_ms()),
        )

    async def fetch_balance(self) -> Dict[str, Any]:
        # Возвращаем словарь ccxt balances; верхний код не полагается на поля
        return await self._call(self._ex.fetch_balance)

    async def fetch_market_info(self, symbol: str) -> Dict[str, Any]:
        # Сырые данные ccxt.market() — далее парсим в MarketInfo там, где нужно
        m = await self._call(self._ex.market, symbol)
        return m

    async def create_market_buy_quote(self, symbol: str, amount_quote: Decimal, client_order_id: Optional[str] = None) -> OrderDTO:
        if amount_quote is None or Decimal(amount_quote) <= 0:
            raise ValidationError("amount_quote must be > 0")
        # Получаем справочник символа
        m = await self._call(self._ex.market, symbol)
        mi = market_info_from_ccxt(symbol, m)
        # Цена для расчёта количества базового актива
        t = await self._call(self._ex.fetch_ticker, symbol)
        price = _to_decimal(t.get("ask") or t.get("last") or t.get("bid"))
        if price <= 0:
            raise BrokerError("invalid price for market buy")
        # Проверяем min notional
        ensure_min_notional_ok(amount_quote, price, mi.min_notional_quote)
        # Рассчитываем количество base
        base_amt = (Decimal(amount_quote) / price)
        base_amt = round_base_step(base_amt, mi.base_step, rounding=ROUND_DOWN)
        if base_amt <= 0:
            raise ValidationError("calculated base amount is too small after rounding")
        # Создаём рыночный ордер
        params = {}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        o = await self._call(self._ex.create_order, symbol, "market", "buy", float(base_amt), None, params)
        filled = _to_decimal(o.get("filled") or 0)
        status = (o.get("status") or "").lower() or "open"
        return OrderDTO(
            id=str(o.get("id")),
            client_order_id=client_order_id or str(o.get("clientOrderId") or ""),
            symbol=symbol,
            side="buy",
            amount=float(_to_decimal(o.get("amount") or base_amt)),
            status=status,
            filled=float(filled),
            timestamp=int(o.get("timestamp") or now_ms()),
        )

    async def create_market_sell_base(self, symbol: str, amount_base: Decimal, client_order_id: Optional[str] = None) -> OrderDTO:
        if amount_base is None or Decimal(amount_base) <= 0:
            raise ValidationError("amount_base must be > 0")
        m = await self._call(self._ex.market, symbol)
        mi = market_info_from_ccxt(symbol, m)
        base_amt = round_base_step(Decimal(amount_base), mi.base_step, rounding=ROUND_DOWN)
        if base_amt <= 0:
            raise ValidationError("amount_base too small after rounding")
        params = {}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        o = await self._call(self._ex.create_order, symbol, "market", "sell", float(base_amt), None, params)
        filled = _to_decimal(o.get("filled") or 0)
        status = (o.get("status") or "").lower() or "open"
        return OrderDTO(
            id=str(o.get("id")),
            client_order_id=client_order_id or str(o.get("clientOrderId") or ""),
            symbol=symbol,
            side="sell",
            amount=float(_to_decimal(o.get("amount") or base_amt)),
            status=status,
            filled=float(filled),
            timestamp=int(o.get("timestamp") or now_ms()),
        )