# src/crypto_ai_bot/core/infrastructure/brokers/ccxt_adapter.py
from __future__ import annotations

import asyncio
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


@dataclass
class CcxtBroker(IBroker):
    exchange_id: str
    api_key: str = ""
    api_secret: str = ""
    enable_rate_limit: bool = True
    sandbox: bool = False
    dry_run: bool = True

    _ex: Any = None
    _markets_loaded: bool = False
    _log = get_logger("broker.ccxt")
    _breaker: CircuitBreaker = field(default_factory=lambda: CircuitBreaker(
        failures_threshold=5, open_timeout_ms=30_000, half_open_successes_to_close=2
    ))

    # --------------------------- bootstrap ---------------------------

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
            try:
                self._ex.set_sandbox_mode(True)
            except Exception:
                pass

    def _ensure_markets(self) -> None:
        if self.dry_run:
            self._markets_loaded = True
            return
        if not self._markets_loaded:
            self._ensure_exchange()
            # ccxt sync call; дергаем loop чтоб избежать RuntimeError в некоторых рантаймах
            asyncio.run_coroutine_threadsafe(asyncio.sleep(0), asyncio.get_running_loop())
            self._ex.load_markets()
            self._markets_loaded = True

    def _reload_markets(self) -> None:
        """Жёсткая перезагрузка справочника рынков (разовый fallback при unknown market)."""
        if self.dry_run:
            self._markets_loaded = True
            return
        self._markets_loaded = False
        self._ensure_markets()

    # --------------------------- helpers ---------------------------

    async def _call_ex(self, fn, *args, **kwargs):
        """
        Унифицированный вызов CCXT c retry + circuit-breaker и маппингом транзиентных ошибок.
        """
        self._ensure_exchange()

        @retry_async(attempts=4, backoff_base=0.25, backoff_factor=2.0, jitter=0.1, max_sleep=2.0, breaker=self._breaker)
        async def _wrapped():
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as exc:
                msg = str(exc).lower()
                # Транзиентные сигналы: таймауты/сеть/лимиты/перегрузка
                if any(s in msg for s in (
                    "timed out", "timeout", "temporar", "rate limit", "ddos", "too many requests",
                    "service unavailable", "exchange not available", "network", "econnreset", "502", "503", "504"
                )):
                    raise TransientError(msg)
                raise
        return await _wrapped()

    def _market_info(self, ex_symbol: str) -> Dict[str, Any]:
        self._ensure_markets()
        if self.dry_run:
            return {
                "precision": {"amount": 8, "price": 8},
                "limits": {"amount": {"min": Decimal("0.00000001")}, "cost": {"min": Decimal("1")}},
            }
        m = self._ex.markets.get(ex_symbol)
        if not m:
            raise ValidationError(f"unknown market {ex_symbol}")
        amount_min = dec(m.get("limits", {}).get("amount", {}).get("min")) if m.get("limits") else None
        cost_min = dec(m.get("limits", {}).get("cost", {}).get("min")) if m.get("limits") else None
        p_amount = int(m.get("precision", {}).get("amount", 8))
        p_price = int(m.get("precision", {}).get("price", 8))
        return {"precision": {"amount": p_amount, "price": p_price},
                "limits": {"amount": {"min": amount_min}, "cost": {"min": cost_min}}}

    # --------------------------- public API ---------------------------

    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        now = now_ms()
        if self.dry_run:
            p = Decimal("100")
            return TickerDTO(symbol=symbol, last=p, bid=p - Decimal("0.1"), ask=p + Decimal("0.1"), timestamp=now)
        try:
            t = await self._call_ex(self._ex.fetch_ticker, ex_symbol)
        except Exception as exc:
            # если рынок не найден — один раз перезагрузим markets и повторим
            if "unknown market" in str(exc).lower():
                try:
                    self._reload_markets()
                    t = await self._call_ex(self._ex.fetch_ticker, ex_symbol)
                except Exception:
                    raise
            else:
                raise
        last = dec(t.get("last") or t.get("close") or 0)
        bid = dec(t.get("bid") or last or 0)
        ask = dec(t.get("ask") or last or 0)
        ts = int(t.get("timestamp") or now)
        return TickerDTO(symbol=symbol, last=last, bid=bid, ask=ask, timestamp=ts)

    async def fetch_balance(self, symbol: str) -> BalanceDTO:
        p = parse_symbol(symbol)
        if self.dry_run:
            return BalanceDTO(free_quote=Decimal("100000"), free_base=Decimal("0"))
        b = await self._call_ex(self._ex.fetch_balance)
        free = (b or {}).get("free", {})
        fq = dec(free.get(p.quote, 0))
        fb = dec(free.get(p.base, 0))
        return BalanceDTO(free_quote=fq, free_base=fb)

    # ---- создание ордеров с clientOrderId идемпотентностью ----

    async def _fetch_order_by_client_id(self, *, ex_symbol: str, client_id: str) -> Optional[Dict[str, Any]]:
        """
        Пробуем вытащить ордер по clientOrderId (если биржа и ccxt это поддерживают).
        Сигнатура ccxt: fetch_order(id, symbol=None, params={})
        Передаём id=None и params={'clientOrderId': ...}
        """
        try:
            return await self._call_ex(self._ex.fetch_order, None, ex_symbol, {"clientOrderId": client_id})
        except Exception:
            return None

    def _is_duplicate_client_id_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(s in msg for s in ("clientorderid", "duplicate", "already exists", "exist order"))

    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Decimal, client_order_id: str) -> OrderDTO:
        if quote_amount <= 0:
            raise ValidationError("quote_amount must be > 0")
        t = await self.fetch_ticker(symbol)
        ask = t.ask or t.last
        if ask <= 0:
            raise TransientError("ticker ask is not available")
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)

        # market info с fallback на reload при unknown market
        try:
            info = self._market_info(ex_symbol)
        except ValidationError:
            self._reload_markets()
            info = self._market_info(ex_symbol)

        p_amount = int(info["precision"]["amount"])
        raw_amount_base = quote_amount / ask
        amount_base_q = q_step(raw_amount_base, p_amount)
        min_amount = info["limits"]["amount"]["min"]
        if min_amount and amount_base_q < min_amount:
            raise ValidationError("calculated base amount is too small after rounding")
        min_cost = info["limits"]["cost"]["min"]
        if min_cost and quote_amount < min_cost:
            raise ValidationError("quote amount below minimum cost")

        client_id = client_order_id or make_client_order_id(self.exchange_id, f"{symbol}-buy")
        if self.dry_run:
            ts = now_ms()
            return OrderDTO(id=f"dry-{client_id}", client_order_id=client_id, symbol=symbol, side="buy",
                            amount=amount_base_q, status="closed", filled=amount_base_q, timestamp=ts)

        try:
            order = await self._call_ex(
                self._ex.create_order, ex_symbol, "market", "buy", float(amount_base_q), None, {"clientOrderId": client_id}
            )
        except Exception as exc:
            if self._is_duplicate_client_id_error(exc):
                # пытаемся подтянуть уже созданный ордер
                fetched = await self._fetch_order_by_client_id(ex_symbol=ex_symbol, client_id=client_id)
                if fetched:
                    return self._map_order(symbol, fetched, fallback_amount=amount_base_q, client_order_id=client_id)
                # нет способа подтянуть — пусть решит внешний ретрай как Transient
                raise TransientError("duplicate clientOrderId, but order not fetchable") from exc
            # другие ошибки — как есть (их уже оборачивает _call_ex при необходимости)
            raise
        return self._map_order(symbol, order, fallback_amount=amount_base_q, client_order_id=client_id)

    async def create_market_sell_base(self, *, symbol: str, base_amount: Decimal, client_order_id: str) -> OrderDTO:
        if base_amount <= 0:
            raise ValidationError("base_amount must be > 0")
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)

        try:
            info = self._market_info(ex_symbol)
        except ValidationError:
            self._reload_markets()
            info = self._market_info(ex_symbol)

        p_amount = int(info["precision"]["amount"])
        amount_base_q = q_step(base_amount, p_amount)
        min_amount = info["limits"]["amount"]["min"]
        if min_amount and amount_base_q < min_amount:
            raise ValidationError("amount_base too small after rounding")

        client_id = client_order_id or make_client_order_id(self.exchange_id, f"{symbol}-sell")
        if self.dry_run:
            ts = now_ms()
            return OrderDTO(id=f"dry-{client_id}", client_order_id=client_id, symbol=symbol, side="sell",
                            amount=amount_base_q, status="closed", filled=amount_base_q, timestamp=ts)

        try:
            order = await self._call_ex(
                self._ex.create_order, ex_symbol, "market", "sell", float(amount_base_q), None, {"clientOrderId": client_id}
            )
        except Exception as exc:
            if self._is_duplicate_client_id_error(exc):
                fetched = await self._fetch_order_by_client_id(ex_symbol=ex_symbol, client_id=client_id)
                if fetched:
                    return self._map_order(symbol, fetched, fallback_amount=amount_base_q, client_order_id=client_id)
                raise TransientError("duplicate clientOrderId, but order not fetchable") from exc
            raise
        return self._map_order(symbol, order, fallback_amount=amount_base_q, client_order_id=client_id)

    async def fetch_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        if self.dry_run:
            return []
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        try:
            return await self._call_ex(self._ex.fetch_open_orders, ex_symbol)
        except Exception:
            return []

    # --------------------------- mapping ---------------------------

    def _map_order(self, symbol: str, o: Dict[str, Any], *, fallback_amount: Decimal, client_order_id: str) -> OrderDTO:
        status = str(o.get("status") or "open")
        filled = dec(o.get("filled") or 0)
        amount = dec(o.get("amount") or fallback_amount)
        ts = int(o.get("timestamp") or now_ms())
        oid = str(o.get("id") or client_order_id)
        side = str(o.get("side") or "buy")
        return OrderDTO(
            id=oid,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            amount=amount,
            status=status,
            filled=filled,
            timestamp=ts,
        )
