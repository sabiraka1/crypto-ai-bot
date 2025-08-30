from __future__ import annotations

import asyncio, time, threading
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

try:
    import ccxt  # type: ignore
except Exception:
    ccxt = None  # type: ignore

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker, TickerDTO, OrderDTO, BalanceDTO
from crypto_ai_bot.core.infrastructure.brokers.symbols import parse_symbol, to_exchange_symbol
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.exceptions import ValidationError, TransientError
from crypto_ai_bot.utils.ids import make_client_order_id
from crypto_ai_bot.utils.decimal import dec, q_step
from crypto_ai_bot.utils.retry import retry_async
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils.metrics import inc


@dataclass
class _Bucket:
    tokens: float = 0.0
    last_refill: float = 0.0


@dataclass
class CcxtBroker(IBroker):
    exchange_id: str
    api_key: str = ""
    api_secret: str = ""
    enable_rate_limit: bool = True
    sandbox: bool = False
    dry_run: bool = True
    wait_close_sec: float = 0.0

    # Новое: лимиты и идемпотентность
    rate_calls_per_sec: float = 0.0     # 0 -> выключить внутренний лимитер
    rate_burst: int = 0                 # вместимость корзины
    idempotency_bucket_ms: int = 60_000

    _ex: Any = None
    _markets_loaded: bool = False
    _log = get_logger("broker.ccxt")
    _breaker: CircuitBreaker = field(default_factory=lambda: CircuitBreaker(
        failures_threshold=5, open_timeout_ms=30_000, half_open_successes_to_close=2
    ))

    _rate_buckets: Dict[str, _Bucket] = field(default_factory=lambda: defaultdict(_Bucket))
    _rate_lock: threading.RLock = field(default_factory=threading.RLock)

    # ---------- bootstrap ----------
    def _ensure_exchange(self) -> None:
        if self.dry_run or self._ex is not None:
            return
        if ccxt is None:
            raise RuntimeError("ccxt is not installed")
        klass = getattr(ccxt, self.exchange_id)
        self._ex = klass({
            "apiKey": self.api_key or None,
            "secret": self.api_secret or None,
            "enableRateLimit": self.enable_rate_limit,
            "options": {"warnOnFetchOpenOrdersWithoutSymbol": False},
        })
        if self.sandbox and hasattr(self._ex, "set_sandbox_mode"):
            try: self._ex.set_sandbox_mode(True)
            except Exception: pass

    def _ensure_markets(self) -> None:
        if self.dry_run:
            self._markets_loaded = True; return
        if not self._markets_loaded:
            self._ensure_exchange()
            asyncio.run_coroutine_threadsafe(asyncio.sleep(0), asyncio.get_running_loop())
            self._ex.load_markets()
            self._markets_loaded = True

    def _reload_markets(self) -> None:
        if self.dry_run: self._markets_loaded = True; return
        self._markets_loaded = False
        self._ensure_markets()

    # ---------- rate limiter ----------
    def _rate_limit(self, key: str) -> None:
        if self.rate_calls_per_sec <= 0 or self.rate_burst <= 0:
            return
        now = time.monotonic()
        with self._rate_lock:
            b = self._rate_buckets[key]
            # инициализация
            if b.last_refill <= 0:
                b.last_refill = now
                b.tokens = float(self.rate_burst)
            # пополнение
            elapsed = max(0.0, now - b.last_refill)
            refill = elapsed * float(self.rate_calls_per_sec)
            b.tokens = min(float(self.rate_burst), b.tokens + refill)
            b.last_refill = now
            # если нет токенов — ждём
            if b.tokens < 1.0:
                need = (1.0 - b.tokens) / float(self.rate_calls_per_sec)
                sleep_for = max(0.0, need)
            else:
                sleep_for = 0.0
                b.tokens -= 1.0
        if sleep_for > 0:
            time.sleep(sleep_for)

    # ---------- ccxt wrapper ----------
    async def _call_ex(self, fn, *args, key_hint: Optional[str] = None, **kwargs):
        self._ensure_exchange()

        @retry_async(attempts=4, backoff_base=0.25, backoff_factor=2.0, jitter=0.1, max_sleep=2.0, breaker=self._breaker)
        async def _wrapped():
            t0 = time.time()
            try:
                k = key_hint or getattr(fn, "__name__", "unknown")
                self._rate_limit(k)
                inc("broker_call_total", fn=getattr(fn, "__name__", "unknown"))
                return await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as exc:
                msg = str(exc).lower()
                if any(s in msg for s in ("timed out","timeout","temporar","rate limit","ddos",
                                           "too many requests","service unavailable","exchange not available",
                                           "network","econnreset","502","503","504")):
                    inc("broker_call_transient_errors_total", fn=getattr(fn, "__name__", "unknown"))
                    raise TransientError(msg)
                inc("broker_call_errors_total", fn=getattr(fn, "__name__", "unknown"))
                raise
            finally:
                dt_ms = int((time.time() - t0) * 1000)
                inc("broker_call_latency_ms_sum", fn=getattr(fn, "__name__", "unknown"), ms=str(dt_ms))
        return await _wrapped()

    # ---------- utils ----------
    def _market_info(self, ex_symbol: str) -> Dict[str, Any]:
        self._ensure_markets()
        if self.dry_run:
            return {"precision":{"amount":8,"price":8},
                    "limits":{"amount":{"min":Decimal("0.00000001")},"cost":{"min":Decimal("1")}}}
        m = self._ex.markets.get(ex_symbol)
        if not m: raise ValidationError(f"unknown market {ex_symbol}")
        amount_min = dec(m.get("limits", {}).get("amount", {}).get("min")) if m.get("limits") else None
        cost_min = dec(m.get("limits", {}).get("cost", {}).get("min")) if m.get("limits") else None
        p_amount = int(m.get("precision", {}).get("amount", 8))
        p_price = int(m.get("precision", {}).get("price", 8))
        return {"precision":{"amount":p_amount,"price":p_price},
                "limits":{"amount":{"min":amount_min},"cost":{"min":cost_min}}}

    def _extract_fee_quote(self, d: Dict[str, Any], quote_ccy: str) -> Decimal:
        total = Decimal("0")
        fee = d.get("fee")
        if fee and str(fee.get("currency") or "").upper() == quote_ccy:
            try: total += dec(fee.get("cost") or 0)
            except Exception: pass
        fees = d.get("fees") or []
        for f in fees:
            if str(f.get("currency") or "").upper() == quote_ccy:
                try: total += dec(f.get("cost") or 0)
                except Exception: pass
        return total

    def _extract_client_order_id_from_trade(self, tr: Dict[str, Any]) -> str:
        if tr.get("clientOrderId"):
            return str(tr["clientOrderId"])
        info = tr.get("info") or {}
        for k in ("clientOrderId","clientOrderID","cOID","text","client_oid","client-id"):
            if k in info and info[k]:
                return str(info[k])
        return ""

    def _extract_client_order_id_from_order(self, od: Dict[str, Any]) -> str:
        if od.get("clientOrderId"):
            return str(od["clientOrderId"])
        info = od.get("info") or {}
        for k in ("clientOrderId","clientOrderID","cOID","text","client_oid","client-id"):
            if k in info and info[k]:
                return str(info[k])
        return ""

    def _deterministic_coid(self, *, symbol: str, side: str, qty: Decimal, unit: str) -> str:
        """
        Детерминированный clientOrderId для ретраев в пределах time-bucket:
        coid = idem:{exchange}:{symbol}:{side}:{unit}:{qty_q}:{bucket}
        """
        bucket = int(now_ms() // max(1, int(self.idempotency_bucket_ms)))
        qty_q = str(q_step(dec(str(qty)), 8))
        return f"idem:{self.exchange_id}:{symbol}:{side}:{unit}:{qty_q}:{bucket}"

    # ---------- public ----------
    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol); now = now_ms()
        if self.dry_run:
            p = Decimal("100"); return TickerDTO(symbol=symbol,last=p,bid=p-Decimal("0.1"),ask=p+Decimal("0.1"),timestamp=now)
        try:
            t = await self._call_ex(self._ex.fetch_ticker, ex_symbol, key_hint=f"fetch_ticker:{symbol}")
        except Exception as exc:
            if "unknown market" in str(exc).lower():
                self._reload_markets()
                t = await self._call_ex(self._ex.fetch_ticker, ex_symbol, key_hint=f"fetch_ticker:{symbol}")
            else:
                raise
        last = dec(t.get("last") or t.get("close") or 0)
        bid  = dec(t.get("bid") or last or 0)
        ask  = dec(t.get("ask") or last or 0)
        ts   = int(t.get("timestamp") or now)
        return TickerDTO(symbol=symbol, last=last, bid=bid, ask=ask, timestamp=ts)

    async def fetch_balance(self, symbol: str) -> BalanceDTO:
        p = parse_symbol(symbol)
        if self.dry_run:
            return BalanceDTO(free_quote=Decimal("100000"), free_base=Decimal("0"))
        b = await self._call_ex(self._ex.fetch_balance, key_hint="fetch_balance:*")
        free = (b or {}).get("free", {})
        fq = dec(free.get(p.quote, 0)); fb = dec(free.get(p.base, 0))
        return BalanceDTO(free_quote=fq, free_base=fb)

    async def fetch_order_by_client_id(self, *, symbol: str, client_order_id: str) -> Optional[Dict[str, Any]]:
        if self.dry_run or not client_order_id:
            return None
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        try:
            # некоторые биржи поддерживают поиск по clientOrderId через params
            return await self._call_ex(self._ex.fetch_order, None, ex_symbol, {"clientOrderId": client_order_id},
                                       key_hint=f"fetch_order:{symbol}")
        except Exception:
            return None

    async def fetch_order_safe(self, order_id: str, symbol: str) -> Optional[Dict[str, Any]]:
        if self.dry_run or not order_id:
            return None
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        try:
            return await self._call_ex(self._ex.fetch_order, order_id, ex_symbol, key_hint=f"fetch_order:{symbol}")
        except Exception:
            return None

    async def fetch_order_trades(self, symbol: str, since_ms: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if self.dry_run:
            return []
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        try:
            params = {}
            if since_ms:
                params["since"] = int(since_ms)
            tr = await self._call_ex(self._ex.fetch_my_trades, ex_symbol, since_ms or None, int(limit), params,
                                     key_hint=f"fetch_my_trades:{symbol}")
            return tr or []
        except Exception:
            return []

    def _is_duplicate_client_id_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(s in msg for s in ("clientorderid","duplicate","already exists","exist order"))

    async def _wait_closed(self, *, order_id: str, ex_symbol: str) -> Optional[Dict[str, Any]]:
        if self.dry_run or self.wait_close_sec <= 0 or not order_id:
            return None
        t0 = time.time()
        delay = 0.5
        last: Optional[Dict[str, Any]] = None
        while (time.time() - t0) < float(self.wait_close_sec):
            try:
                od = await self._call_ex(self._ex.fetch_order, order_id, ex_symbol, key_hint=f"fetch_order:*")
                last = od
                st = str(od.get("status") or "").lower()
                if st == "closed":
                    return od
            except Exception:
                pass
            await asyncio.sleep(delay)
        return last

    def _map_order(self, symbol: str, o: Dict[str, Any], *, fallback_amount: Decimal, client_order_id: str) -> OrderDTO:
        status = str(o.get("status") or "open")
        filled = dec(o.get("filled") or 0)
        amount = dec(o.get("amount") or fallback_amount)
        ts = int(o.get("timestamp") or now_ms())
        oid = str(o.get("id") or client_order_id)
        side = str(o.get("side") or "buy")
        px = dec(o.get("price") or 0)
        cost = dec(o.get("cost") or 0)
        quote = parse_symbol(symbol).quote
        fee_q = self._extract_fee_quote(o, quote_ccy=quote)
        return OrderDTO(
            id=oid,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            amount=amount,
            status=status,
            filled=filled,
            timestamp=ts,
            price=px if px > 0 else None,
            cost=cost if cost > 0 else None,
            fee_quote=fee_q,
        )

    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Decimal, client_order_id: str = "") -> OrderDTO:
        if quote_amount <= 0: raise ValidationError("quote_amount must be > 0")
        t = await self.fetch_ticker(symbol); ask = t.ask or t.last
        if ask <= 0: raise TransientError("ticker ask is not available")
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        try: info = self._market_info(ex_symbol)
        except ValidationError:
            self._reload_markets(); info = self._market_info(ex_symbol)
        p_amount = int(info["precision"]["amount"])
        raw_amount_base = quote_amount / ask
        amount_base_q = q_step(raw_amount_base, p_amount)
        min_amount = info["limits"]["amount"]["min"]
        if min_amount and amount_base_q < min_amount: raise ValidationError("calculated base amount is too small after rounding")
        min_cost = info["limits"]["cost"]["min"]
        if min_cost and quote_amount < min_cost: raise ValidationError("quote amount below minimum cost")
        # детерминированный client id (если не передали)
        client_id = client_order_id or self._deterministic_coid(symbol=symbol, side="buy", qty=quote_amount, unit="quote")
        if self.dry_run:
            ts = now_ms()
            return OrderDTO(id=f"dry-{client_id}", client_order_id=client_id, symbol=symbol, side="buy",
                            amount=amount_base_q, status="closed", filled=amount_base_q, timestamp=ts, fee_quote=Decimal("0"))
        try:
            order = await self._call_ex(self._ex.create_order, ex_symbol, "market", "buy", float(amount_base_q), None,
                                        {"clientOrderId": client_id}, key_hint=f"create_order:{symbol}")
        except Exception as exc:
            if self._is_duplicate_client_id_error(exc):
                fetched = await self.fetch_order_by_client_id(symbol=symbol, client_order_id=client_id)
                if fetched:
                    closed = await self._wait_closed(order_id=str(fetched.get("id") or ""), ex_symbol=ex_symbol)
                    return self._map_order(symbol, closed or fetched, fallback_amount=amount_base_q, client_order_id=client_id)
                raise TransientError("duplicate clientOrderId, but order not fetchable") from exc
            raise
        closed = await self._wait_closed(order_id=str(order.get("id") or ""), ex_symbol=ex_symbol)
        return self._map_order(symbol, closed or order, fallback_amount=amount_base_q, client_order_id=client_id)

    async def create_market_sell_base(self, *, symbol: str, base_amount: Decimal, client_order_id: str = "") -> OrderDTO:
        if base_amount <= 0: raise ValidationError("base_amount must be > 0")
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        try: info = self._market_info(ex_symbol)
        except ValidationError:
            self._reload_markets(); info = self._market_info(ex_symbol)
        p_amount = int(info["precision"]["amount"])
        amount_base_q = q_step(base_amount, p_amount)
        min_amount = info["limits"]["amount"]["min"]
        if min_amount and amount_base_q < min_amount: raise ValidationError("amount_base too small after rounding")
        client_id = client_order_id or self._deterministic_coid(symbol=symbol, side="sell", qty=amount_base_q, unit="base")
        if self.dry_run:
            ts = now_ms()
            return OrderDTO(id=f"dry-{client_id}", client_order_id=client_id, symbol=symbol, side="sell",
                            amount=amount_base_q, status="closed", filled=amount_base_q, timestamp=ts, fee_quote=Decimal("0"))
        try:
            order = await self._call_ex(self._ex.create_order, ex_symbol, "market", "sell", float(amount_base_q), None,
                                        {"clientOrderId": client_id}, key_hint=f"create_order:{symbol}")
        except Exception as exc:
            if self._is_duplicate_client_id_error(exc):
                fetched = await self.fetch_order_by_client_id(symbol=symbol, client_order_id=client_id)
                if fetched:
                    closed = await self._wait_closed(order_id=str(fetched.get("id") or ""), ex_symbol=ex_symbol)
                    return self._map_order(symbol, closed or fetched, fallback_amount=amount_base_q, client_order_id=client_id)
                raise TransientError("duplicate clientOrderId, but order not fetchable") from exc
            raise
        closed = await self._wait_closed(order_id=str(order.get("id") or ""), ex_symbol=ex_symbol)
        return self._map_order(symbol, closed or order, fallback_amount=amount_base_q, client_order_id=client_id)

    async def fetch_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        if self.dry_run: return []
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        try:
            return await self._call_ex(self._ex.fetch_open_orders, ex_symbol, key_hint=f"fetch_open_orders:{symbol}")
        except Exception:
            return []
