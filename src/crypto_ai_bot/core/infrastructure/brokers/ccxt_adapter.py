﻿from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Callable, Awaitable

from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc, observe

_log = get_logger("broker.ccxt")


class BrokerError(Exception): ...
class InsufficientFunds(BrokerError): ...
class RateLimited(BrokerError): ...
class OrderNotFound(BrokerError): ...
class ValidationError(BrokerError): ...
class ExchangeUnavailable(BrokerError): ...


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
        self._markets: dict[str, dict] = {}
        self._sym_to_gate: dict[str, str] = {}
        self._gate_to_sym: dict[str, str] = {}

        self._cb_ticker = CircuitBreaker(name="ticker", failure_threshold=5, reset_timeout_sec=10.0)
        self._cb_balance = CircuitBreaker(name="balance", failure_threshold=5, reset_timeout_sec=10.0)
        self._cb_create = CircuitBreaker(name="create", failure_threshold=3, reset_timeout_sec=15.0)
        self._cb_order = CircuitBreaker(name="order", failure_threshold=5, reset_timeout_sec=10.0)

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
    def _quant(x: Decimal, step: Decimal | None) -> Decimal:
        if not step or step <= 0:
            return x
        return (x / step).to_integral_value(rounding=ROUND_DOWN) * step

    def _apply_precision(
        self, sym: str, *, amount: Decimal | None, price: Decimal | None
    ) -> tuple[Decimal | None, Decimal | None]:
        md = self._market_desc(sym)
        p_amt = amount
        p_pr = price
        try:
            if amount is not None:
                step = None
                prec = md.get("precision", {}) or {}
                limits = md.get("limits", {}) or {}
                if prec.get("amount"):
                    step = dec(str(prec["amount"]))
                elif "amount" in limits and "min" in limits["amount"]:
                    step = dec(str(limits["amount"]["min"]))
                p_amt = self._quant(amount, step)
            if price is not None:
                step = None
                prec = md.get("precision", {}) or {}
                if prec.get("price"):
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
        if "not found" in msg or "cancelled" in msg:
            return OrderNotFound(msg)
        if "429" in msg or "rate limit" in msg:
            return RateLimited(msg)
        if "503" in msg or "temporarily unavailable" in msg:
            return ExchangeUnavailable(msg)
        if "invalid" in msg or "precision" in msg or "amount" in msg or "min" in msg or "notional" in msg:
            return ValidationError(msg)
        return BrokerError(msg)

    def _check_min_notional(self, sym: str, *, amount: Decimal, price: Decimal) -> None:
        md = self._market_desc(sym)
        notional = amount * price
        limits = md.get("limits", {}) or {}
        min_notional = None
        if "cost" in limits and "min" in limits["cost"]:
            try:
                min_notional = dec(str(limits["cost"]["min"]))
            except Exception:
                min_notional = None
        if min_notional and min_notional > 0 and notional < min_notional:
            raise ValidationError(f"minNotional:{notional}<{min_notional}")

    async def _with_cb(self, cb: CircuitBreaker, coro_fn: Callable[[], Awaitable[Any]]) -> Any:
        async with cb:
            return await coro_fn()

    async def fetch_ticker(self, symbol: str) -> Any:
        await self._ensure_markets()
        gate = self._sym_to_gate.get(symbol) or self._to_gate(symbol)
        await self._bucket.acquire()
        try:
            t0 = asyncio.get_event_loop().time()
            res = await self._with_cb(self._cb_ticker, lambda: self.exchange.fetch_ticker(gate))
            observe("broker.request.ms", (asyncio.get_event_loop().time() - t0) * 1000.0, {"fn": "fetch_ticker"})
            return res
        except Exception as exc:
            inc("broker.request.error", fn="fetch_ticker")
            raise self._map_error(exc) from exc

    async def fetch_balance(self, symbol: str) -> Any:
        await self._ensure_markets()
        base, quote = symbol.split("/")
        await self._bucket.acquire()
        try:
            t0 = asyncio.get_event_loop().time()
            bal = await self._with_cb(self._cb_balance, lambda: self.exchange.fetch_balance())
            observe("broker.request.ms", (asyncio.get_event_loop().time() - t0) * 1000.0, {"fn": "fetch_balance"})
            acct_base = bal.get(base, {}) or {}
            acct_quote = bal.get(quote, {}) or {}
            return {
                "free_base": dec(str(acct_base.get("free", 0) or 0)),
                "free_quote": dec(str(acct_quote.get("free", 0) or 0)),
            }
        except Exception as exc:
            inc("broker.request.error", fn="fetch_balance")
            raise self._map_error(exc) from exc

    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Decimal, client_order_id: str | None = None) -> Any:
        await self._ensure_markets()
        t = await self.fetch_ticker(symbol)
        ask = dec(str(t.get("ask") or "0")) or dec(str(t.get("last") or "0"))
        if ask <= 0:
            raise ValidationError("ticker_ask_invalid")
        base_amount = quote_amount / ask
        base_amount, _ = self._apply_precision(symbol, amount=base_amount, price=None)
        if base_amount is None:
            raise ValidationError("precision_application_failed")
        self._check_min_notional(symbol, amount=base_amount, price=ask)
        gate = self._sym_to_gate.get(symbol) or self._to_gate(symbol)
        params = {"type": "market", "timeInForce": "IOC"}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        await self._bucket.acquire()
        try:
            t0 = asyncio.get_event_loop().time()
            order = await self._with_cb(self._cb_create, lambda: self.exchange.create_order(gate, "market", "buy", float(base_amount), None, params))
            observe("broker.request.ms", (asyncio.get_event_loop().time() - t0) * 1000.0, {"fn": "create_buy"})
            return order
        except Exception as exc:
            inc("broker.request.error", fn="create_buy")
            raise self._map_error(exc) from exc

    async def create_market_sell_base(self, *, symbol: str, base_amount: Decimal, client_order_id: str | None = None) -> Any:
        await self._ensure_markets()
        t = await self.fetch_ticker(symbol)
        bid = dec(str(t.get("bid") or "0")) or dec(str(t.get("last") or "0"))
        if bid <= 0:
            raise ValidationError("ticker_bid_invalid")
        b_amt, _ = self._apply_precision(symbol, amount=base_amount, price=None)
        if b_amt is None:
            raise ValidationError("precision_application_failed")
        self._check_min_notional(symbol, amount=b_amt, price=bid)
        gate = self._sym_to_gate.get(symbol) or self._to_gate(symbol)
        params = {"type": "market", "timeInForce": "IOC"}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        await self._bucket.acquire()
        try:
            t0 = asyncio.get_event_loop().time()
            order = await self._with_cb(self._cb_create, lambda: self.exchange.create_order(gate, "market", "sell", float(b_amt), None, params))
            observe("broker.request.ms", (asyncio.get_event_loop().time() - t0) * 1000.0, {"fn": "create_sell"})
            return order
        except Exception as exc:
            inc("broker.request.error", fn="create_sell")
            raise self._map_error(exc) from exc

    async def fetch_order(self, *, symbol: str, broker_order_id: str) -> Any:
        await self._ensure_markets()
        gate = self._sym_to_gate.get(symbol) or self._to_gate(symbol)
        await self._bucket.acquire()
        try:
            t0 = asyncio.get_event_loop().time()
            res = await self._with_cb(self._cb_order, lambda: self.exchange.fetch_order(broker_order_id, gate))
            observe("broker.request.ms", (asyncio.get_event_loop().time() - t0) * 1000.0, {"fn": "fetch_order"})
            return res
        except Exception as exc:
            inc("broker.request.error", fn="fetch_order")
            raise self._map_error(exc) from exc
