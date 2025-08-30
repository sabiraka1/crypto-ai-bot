from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("broker.ccxt")

# === Вспомогательный токен-бакет (простая реализация) ===
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
    exchange: Any           # ccxt.async_support.<exchange>
    settings: Any

    def __post_init__(self) -> None:
        rps = float(getattr(self.settings, "BROKER_RATE_RPS", 8))   # по умолчанию 8 запросов/сек
        cap = int(getattr(self.settings, "BROKER_RATE_BURST", 16))
        self._bucket = _TokenBucket(rps, cap)
        self._m_lock = asyncio.Lock()
        self._markets: Dict[str, dict] = {}
        self._sym_to_gate: Dict[str, str] = {}  # "BTC/USDT" -> "btc_usdt"
        self._gate_to_sym: Dict[str, str] = {}  # обратный маппинг

    # === Символы: canonical <-> gateio native ===
    @staticmethod
    def _to_gate(sym: str) -> str:
        # BTC/USDT -> btc_usdt ; ETH/USDT -> eth_usdt
        base, quote = sym.split("/")
        return f"{base.lower()}_{quote.lower()}"

    @staticmethod
    def _from_gate(g: str) -> str:
        # btc_usdt -> BTC/USDT
        base, quote = g.split("_")
        return f"{base.upper()}/{quote.upper()}"

    async def _ensure_markets(self) -> None:
        if self._markets:
            return
        await self._bucket.acquire()
        mk = await self.exchange.load_markets()
        self._markets = mk or {}
        # построим карту символов
        for k in self._markets.keys():
            if "_" in k and "/" not in k:
                can = self._from_gate(k)
                self._sym_to_gate[can] = k
                self._gate_to_sym[k] = can
            elif "/" in k:
                self._sym_to_gate[k] = self._to_gate(k)
                self._gate_to_sym[self._to_gate(k)] = k

    def _q(self, sym: str) -> dict:
        # Возвращает дескриптор рынка (precision/limits) для canonical символа
        can = sym
        if can not in self._sym_to_gate:
            # fallback: построить маппинг на лету
            self._sym_to_gate[can] = self._to_gate(can)
        gate = self._sym_to_gate[can]
        md = self._markets.get(gate) or self._markets.get(can) or {}
        return md

    @staticmethod
    def _quant(x: Decimal, step: Optional[Decimal]) -> Decimal:
        if not step or step <= 0:
            return x
        # округление вниз к сетке
        q = (x / step).to_integral_value(rounding=ROUND_DOWN) * step
        return q

    def _apply_precision(self, sym: str, *, amount: Optional[Decimal], price: Optional[Decimal]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        md = self._q(sym)
        p_amt = None
        p_pr = None
        if amount is not None:
            step = None
            try:
                step = dec(str(md.get("precision", {}).get("amount"))) if md.get("precision", {}).get("amount") else None
                if not step:
                    step = dec(str(md.get("limits", {}).get("amount", {}).get("min"))) if md.get("limits", {}).get("amount", {}).get("min") else None
            except Exception:
                step = None
            p_amt = self._quant(amount, step)
        if price is not None:
            step = None
            try:
                step = dec(str(md.get("precision", {}).get("price"))) if md.get("precision", {}).get("price") else None
            except Exception:
                step = None
            p_pr = self._quant(price, step)
        return p_amt, p_pr

    # === Публичные методы ===
    async def fetch_ticker(self, symbol: str) -> Any:
        await self._ensure_markets()
        gate = self._sym_to_gate.get(symbol) or self._to_gate(symbol)
        await self._bucket.acquire()
        return await self.exchange.fetch_ticker(gate)

    async def fetch_balance(self, symbol: str) -> Any:
        await self._ensure_markets()
        base, quote = symbol.split("/")
        await self._bucket.acquire()
        bal = await self.exchange.fetch_balance()
        # Приведём к нашему DTO: free_base/free_quote
        acct_base = bal.get(base, {}) or {}
        acct_quote = bal.get(quote, {}) or {}
        return {
            "free_base": dec(str(acct_base.get("free", 0) or 0)),
            "free_quote": dec(str(acct_quote.get("free", 0) or 0)),
        }

    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Decimal,
                                      client_order_id: Optional[str] = None) -> Any:
        await self._ensure_markets()
        _, p_price = self._apply_precision(symbol, amount=None, price=None)  # пусть цена — рыночная
        q_amt, _ = self._apply_precision(symbol, amount=quote_amount, price=None)
        gate = self._sym_to_gate.get(symbol) or self._to_gate(symbol)
        params = {"type": "market", "timeInForce": "IOC"}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        await self._bucket.acquire()
        try:
            return await self.exchange.create_order(gate, "market", "buy", None, float(q_amt), params)
        except Exception as exc:
            _log.error("create_market_buy_failed", extra={"symbol": symbol, "error": str(exc)})
            raise

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
            return await self.exchange.create_order(gate, "market", "sell", float(b_amt), None, params)
        except Exception as exc:
            _log.error("create_market_sell_failed", extra={"symbol": symbol, "error": str(exc)})
            raise
