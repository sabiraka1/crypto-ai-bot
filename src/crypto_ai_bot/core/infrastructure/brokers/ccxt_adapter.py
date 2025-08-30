from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc, observe

_log = get_logger("broker.ccxt")


class BrokerError(Exception): ...
class InsufficientFunds(BrokerError): ...
class RateLimited(BrokerError): ...
class OrderNotFound(BrokerError): ...
class ValidationError(BrokerError): ...


class _TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: int) -> None:
        self._rate = float(rate_per_sec)
        self._cap = int(capacity)
        self._tokens = float(capacity)
        self._last = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()

    async def acquire(self, need: float = 1.0) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = max(0.0, now - self._last)
            self._last = now
            self._tokens = min(self._cap, self._tokens + elapsed * self._rate)
            if self._tokens >= need:
                self._tokens -= need
                return
            wait_s = (need - self._tokens) / self._rate if self._rate > 0 else 0.1
        await asyncio.sleep(wait_s)


@dataclass
class CcxtBroker:
    exchange: Any
    settings: Any

    def __post_init__(self) -> None:
        rps = float(getattr(self.settings, "BROKER_RATE_RPS", 8))
        cap = int(getattr(self.settings, "BROKER_RATE_BURST", 16))
        self._bucket = _TokenBucket(rps, cap)
        self._markets: Dict[str, dict] = {}
        self._sym_to_gate: Dict[str, str] = {}
        self._gate_to_sym: Dict[str, str] = {}

    @staticmethod
    def _to_gate(sym: str) -> str:
        base, quote = sym.split("/")
        return f"{base.lower()}_{quote.lower()}"

    @staticmethod
    def _from_gate(g: str) -> str:
        base, quote = g.split("_")
        return f"{base.upper()}/{quote.upper()}"

    async def _ensure_markets(self) -> None:
        if self._markets:
            return
        await self._bucket.acquire()
        mk = await self.exchange.load_markets()
        self._markets = mk or {}
        for k in self._markets.keys():
            if "_" in k and "/" not in k:
                can = self._from_gate(k)
                self._sym_to_gate[can] = k
                self._gate_to_sym[k] = can
            elif "/" in k:
                g = self._to_gate(k)
                self._sym_to_gate[k] = g
                self._gate_to_sym[g] = k

    def _market_desc(self, sym: str) -> dict:
        can = sym
        gate = self._sym_to_gate.get(can) or self._to_gate(can)
        return self._markets.get(gate) or self._markets.get(can) or {}

    @staticmethod
    def _quant(x: Decimal, step: Optional[Decimal]) -> Decimal:
        if not step or step <= 0:
            return x
        return (x / step).to_integral_value(rounding=ROUND_DOWN) * step

    def _apply_precision(self, sym: str, *, amount: Optional[Decimal], price: Optional[Decimal]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        md = self._market_desc(sym)
        p_amt = amount
        p_pr = price
        try:
            if amount is not None:
                step = None
                prec = md.get("precision", {}) or {}
                limits = md.get("limits", {}) or {}
                if "amount" in prec and prec["amount"]:
                    step = dec(str(prec["amount"]))
                elif "amount" in limits and "min" in limits["amount"]:
                    step = dec(str(limits["amount"]["min"]))
                p_amt = self._quant(amount, step)
            if price is not None:
                step = None
                prec = md.get("precision", {}) or {}
                if "price" in prec and prec["price"]:
                    step = dec(str(prec["price"]))
                p_pr = self._quant(price, step)
        except Exception:
            pass
        return p_amt, p_pr

    @staticmethod
    def _map_error(exc: Exception) -> BrokerError:
        msg = str(exc).lower()
        if "insufficient" in msg or "balance" in msg:
            return InsufficientFunds(msg)
        if "not found" in msg:
            return OrderNotFound(msg)
        if "429" in msg or "rate limit" in msg:
            return RateLimited(msg)
        if "invalid" in msg or "precision" in msg or "amount" in msg or "min" in msg:
            return ValidationError(msg)
        return BrokerError(msg)

    async def fetch_ticker(self, symbol: str) -> Any:
        await self._ensure_markets()
        gate = self._sym_to_gate.get(symbol) or self._to_gate(symbol)
        await self._bucket.acquire()
        try:
            t0 = asyncio.get_event_loop().time()
            res = await self.exchange.fetch_ticker(gate)
            observe("broker.request.ms", (asyncio.get_event_loop().time() - t0) * 1000.0, {"fn": "fetch_ticker"})
            return res
        except Exception as exc:
            inc("broker.request.error", {"fn": "fetch_ticker"})
            raise self._map_error(exc)

    async def fetch_balance(self, symbol: str) -> Any:
        await self._ensure_markets()
        base, quote = symbol.split("/")
        await self._bucket.acquire()
        try:
            t0 = asyncio.get_event_loop().time()
            bal = await self.exchange.fetch_balance()
            observe("broker.request.ms", (asyncio.get_event_loop().time() - t0) * 1000.0, {"fn": "fetch_balance"})
            acct_base = bal.get(base, {}) or {}
            acct_quote = bal.get(quote, {}) or {}
            return {
                "free_base": dec(str(acct_base.get("free", 0) or 0)),
                "free_quote": dec(str(acct_quote.get("free", 0) or 0)),
            }
        except Exception as exc:
            inc("broker.request.error", {"fn": "fetch_balance"})
            raise self._map_error(exc)

    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Decimal,
                                      client_order_id: Optional[str] = None) -> Any:
        """
        Gate/CCXT: для MARKET BUY нужен amount в БАЗОВОЙ.
        Считаем base_amount = quote_amount / ask и квантуем по сетке amount.
        """
        await self._ensure_markets()
        # получаем актуальный ask
        t = await self.fetch_ticker(symbol)
        ask = dec(str(t.get("ask") or "0"))
        if ask <= 0:
            # fallback: last
            ask = dec(str(t.get("last") or "0"))
        if ask <= 0:
            raise ValidationError("ticker_ask_invalid")

        base_amount = quote_amount / ask
        base_amount, _ = self._apply_precision(symbol, amount=base_amount, price=None)

        gate = self._sym_to_gate.get(symbol) or self._to_gate(symbol)
        params = {"type": "market", "timeInForce": "IOC"}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        await self._bucket.acquire()
        try:
            t0 = asyncio.get_event_loop().time()
            order = await self.exchange.create_order(gate, "market", "buy", float(base_amount), None, params)
            observe("broker.request.ms", (asyncio.get_event_loop().time() - t0) * 1000.0, {"fn": "create_buy"})
            return order
        except Exception as exc:
            inc("broker.request.error", {"fn": "create_buy"})
            raise self._map_error(exc)

    async def create_market_sell_base(self, *, symbol: str, base_amount: Decimal,
                                      client_order_id: Optional[str] = None) -> Any:
        await self._ensure_markets()
        b_amt, _ = self._apply_precision(symbol, amount=base_amount, price=None)
        gate = self._sym_to_gate.get(symbol) or self._to_gate(symbol)
        params = {"type": "market", "timeInForce": "IOC"}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        await self._bucket.acquire()
        try:
            t0 = asyncio.get_event_loop().time()
            order = await self.exchange.create_order(gate, "market", "sell", float(b_amt), None, params)
            observe("broker.request.ms", (asyncio.get_event_loop().time() - t0) * 1000.0, {"fn": "create_sell"})
            return order
        except Exception as exc:
            inc("broker.request.error", {"fn": "create_sell"})
            raise self._map_error(exc)
