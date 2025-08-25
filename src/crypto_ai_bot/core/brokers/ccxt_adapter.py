from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, Any, List

try:
    import ccxt  # type: ignore
except Exception:  # ccxt не обязателен для unit-тестов
    ccxt = None  # noqa: N816

from .base import IBroker, TickerDTO, OrderDTO, BalanceDTO
from .symbols import parse_symbol, to_exchange_symbol
from ...utils.logging import get_logger
from ...utils.time import now_ms
from ...utils.exceptions import ValidationError, TransientError
from ...utils.ids import make_client_order_id


def _q_step(x: Decimal, step_pow10: int) -> Decimal:
    q = Decimal(10) ** -step_pow10
    return x.quantize(q, rounding=ROUND_DOWN)


@dataclass
class CcxtBroker(IBroker):
    """Надёжная обёртка CCXT с единой семантикой BUY_QUOTE / SELL_BASE.
    Совместима с `IBroker`:
      - `fetch_ticker(symbol) -> TickerDTO`
      - `fetch_balance(symbol) -> BalanceDTO` (только base/quote пары)
      - `create_market_buy_quote(symbol, quote_amount, client_order_id)`
      - `create_market_sell_base(symbol, base_amount, client_order_id)`
    """

    exchange_id: str
    api_key: str = ""
    api_secret: str = ""
    enable_rate_limit: bool = True
    sandbox: bool = False
    dry_run: bool = True

    _ex: Any = None
    _markets_loaded: bool = False
    _log = get_logger("broker.ccxt")

    # --- lifecycle -------------------------------------------------------------
    def _ensure_exchange(self) -> None:
        if self.dry_run:
            return
        if self._ex is not None:
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
            self._ex.load_markets()
            self._markets_loaded = True

    def _market_info(self, ex_symbol: str) -> Dict[str, Any]:
        """Возвращает precision/limits. Dry-run: безопасные дефолты."""
        self._ensure_markets()
        if self.dry_run:
            return {
                "precision": {"amount": 8, "price": 8},
                "limits": {"amount": {"min": Decimal("0.00000001")}, "cost": {"min": Decimal("1")}},
            }
        m = self._ex.markets.get(ex_symbol)
        if not m:
            raise ValidationError(f"unknown market {ex_symbol}")
        amount_min = Decimal(str(m.get("limits", {}).get("amount", {}).get("min", 0))) if m.get("limits") else None
        cost_min = Decimal(str(m.get("limits", {}).get("cost", {}).get("min", 0))) if m.get("limits") else None
        p_amount = int(m.get("precision", {}).get("amount", 8))
        p_price = int(m.get("precision", {}).get("price", 8))
        return {"precision": {"amount": p_amount, "price": p_price}, "limits": {"amount": {"min": amount_min}, "cost": {"min": cost_min}}}

    # --- interface -------------------------------------------------------------
    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        now = now_ms()
        if self.dry_run:
            p = Decimal("100")
            return TickerDTO(symbol=symbol, last=p, bid=p - Decimal("0.1"), ask=p + Decimal("0.1"), timestamp=now)
        try:
            self._ensure_exchange()
            t = await self._ex.fetch_ticker(ex_symbol)
            last = Decimal(str(t.get("last") or t.get("close") or 0))
            bid = Decimal(str(t.get("bid") or last or 0))
            ask = Decimal(str(t.get("ask") or last or 0))
            ts = int(t.get("timestamp") or now)
            return TickerDTO(symbol=symbol, last=last, bid=bid, ask=ask, timestamp=ts)
        except getattr(ccxt, "RateLimitExceeded", Exception) as exc:  # type: ignore[attr-defined]
            raise TransientError(str(exc)) from exc
        except Exception as exc:
            raise TransientError(str(exc)) from exc

    async def fetch_balance(self, symbol: str) -> BalanceDTO:
        p = parse_symbol(symbol)
        if self.dry_run:
            # по умолчанию — денег достаточно для тестов
            return BalanceDTO(free_quote=Decimal("100000"), free_base=Decimal("0"))
        try:
            self._ensure_exchange()
            b = await self._ex.fetch_balance()
            free = (b or {}).get("free", {})
            fq = Decimal(str(free.get(p.quote, 0)))
            fb = Decimal(str(free.get(p.base, 0)))
            return BalanceDTO(free_quote=fq, free_base=fb)
        except getattr(ccxt, "RateLimitExceeded", Exception) as exc:  # type: ignore[attr-defined]
            raise TransientError(str(exc)) from exc
        except Exception as exc:
            raise TransientError(str(exc)) from exc

    async def create_market_buy_quote(
        self, *, symbol: str, quote_amount: Decimal, client_order_id: str
    ) -> OrderDTO:
        if quote_amount <= 0:
            raise ValidationError("quote_amount must be > 0")
        t = await self.fetch_ticker(symbol)
        ask = t.ask or t.last
        if ask <= 0:
            raise TransientError("ticker ask is not available")
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        info = self._market_info(ex_symbol)
        p_amount = int(info["precision"]["amount"])  # precision для amount
        raw_amount_base = quote_amount / ask
        amount_base_q = _q_step(raw_amount_base, p_amount)
        min_amount = info["limits"]["amount"]["min"]
        if min_amount and amount_base_q < min_amount:
            raise ValidationError("calculated base amount is too small after rounding")
        min_cost = info["limits"]["cost"]["min"]
        if min_cost and quote_amount < min_cost:
            raise ValidationError("quote amount below minimum cost")
        client_id = client_order_id or make_client_order_id(self.exchange_id, f"{symbol}:buy")
        if self.dry_run:
            ts = now_ms()
            return OrderDTO(
                id=f"dry-{client_id}", client_order_id=client_id, symbol=symbol, side="buy",
                amount=amount_base_q, status="closed", filled=amount_base_q, timestamp=ts,
            )
        try:
            self._ensure_exchange()
            order = await self._ex.create_order(ex_symbol, "market", "buy", float(amount_base_q), None, {"clientOrderId": client_id})
            return self._map_order(symbol, order, fallback_amount=amount_base_q, client_order_id=client_id)
        except getattr(ccxt, "RateLimitExceeded", Exception) as exc:  # type: ignore[attr-defined]
            raise TransientError(str(exc)) from exc
        except getattr(ccxt, "InvalidOrder", Exception) as exc:  # type: ignore[attr-defined]
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            raise TransientError(str(exc)) from exc

    async def create_market_sell_base(
        self, *, symbol: str, base_amount: Decimal, client_order_id: str
    ) -> OrderDTO:
        if base_amount <= 0:
            raise ValidationError("base_amount must be > 0")
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        info = self._market_info(ex_symbol)
        p_amount = int(info["precision"]["amount"])  # precision для amount
        amount_base_q = _q_step(base_amount, p_amount)
        min_amount = info["limits"]["amount"]["min"]
        if min_amount and amount_base_q < min_amount:
            raise ValidationError("amount_base too small after rounding")
        client_id = client_order_id or make_client_order_id(self.exchange_id, f"{symbol}:sell")
        if self.dry_run:
            ts = now_ms()
            return OrderDTO(
                id=f"dry-{client_id}", client_order_id=client_id, symbol=symbol, side="sell",
                amount=amount_base_q, status="closed", filled=amount_base_q, timestamp=ts,
            )
        try:
            self._ensure_exchange()
            order = await self._ex.create_order(ex_symbol, "market", "sell", float(amount_base_q), None, {"clientOrderId": client_id})
            return self._map_order(symbol, order, fallback_amount=amount_base_q, client_order_id=client_id)
        except getattr(ccxt, "RateLimitExceeded", Exception) as exc:  # type: ignore[attr-defined]
            raise TransientError(str(exc)) from exc
        except getattr(ccxt, "InvalidOrder", Exception) as exc:  # type: ignore[attr-defined]
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            raise TransientError(str(exc)) from exc

    async def fetch_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Опциональный метод для сверки. Dry-run — пустой список."""
        if self.dry_run:
            return []
        ex_symbol = to_exchange_symbol(self.exchange_id, symbol)
        self._ensure_exchange()
        try:
            return await self._ex.fetch_open_orders(ex_symbol)
        except Exception:
            return []

    # --- mapping ---------------------------------------------------------------
    def _map_order(self, symbol: str, o: Dict[str, Any], *, fallback_amount: Decimal, client_order_id: str) -> OrderDTO:
        status = str(o.get("status") or "open")
        filled = Decimal(str(o.get("filled") or 0))
        amount = Decimal(str(o.get("amount") or fallback_amount))
        ts = int(o.get("timestamp") or now_ms())
        oid = str(o.get("id") or client_order_id)
        side = str(o.get("side") or "buy")
        # fee (если есть) — логируем, но не ломаем DTO
        fee = o.get("fee") or {}
        if fee:
            try:
                fee_cost = Decimal(str(fee.get("cost") or 0))
                fee_code = str(fee.get("currency") or "")
                self._log.info("order_fee_info", extra={"id": oid, "fee_cost": str(fee_cost), "fee_currency": fee_code})
            except Exception:
                pass
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