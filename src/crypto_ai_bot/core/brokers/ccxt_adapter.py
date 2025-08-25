from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, Any

try:
    import ccxt  # type: ignore
except Exception:  # ccxt не обязателен для тестов — dry-run переживет его отсутствие
    ccxt = None  # noqa: N816

from ..brokers.base import IBroker, TickerDTO, OrderDTO
from ..brokers.symbols import parse_symbol, to_exchange_symbol
from ...utils.logging import get_logger
from ...utils.time import now_ms
from ...utils.exceptions import ValidationError, TransientError
from ...utils.ids import make_client_order_id


def _q(x: Decimal, nd: int) -> Decimal:
    """Квантование до nd знаков после запятой (вниз)."""
    q = Decimal(10) ** -nd
    return x.quantize(q, rounding=ROUND_DOWN)


@dataclass
class CcxtBroker(IBroker):
    """
    Упрощённая/надёжная обёртка CCXT с:
    - верной семантикой BUY_QUOTE / SELL_BASE
    - учётом прецизии и минимальных лимитов
    - поддержкой partial fills (возврат filled < amount)
    - учётом комиссий, если биржа их вернула
    - dry_run=True по умолчанию (локальные тесты без сети)
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

    # --- lifecycle helpers ---
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
        """Возвращает info о символе из ccxt (precision/limits). В dry-run — безопасные дефолты."""
        self._ensure_markets()
        if self.dry_run:
            # дефолтные границы: 8/8 знаков и минимума нет — всё проверяют тесты расчётов
            return {
                "precision": {"amount": 8, "price": 8},
                "limits": {
                    "amount": {"min": Decimal("0.00000001")},
                    "cost": {"min": Decimal("1")},
                },
            }
        m = self._ex.markets.get(ex_symbol)
        if not m:
            raise ValidationError(f"unknown market {ex_symbol}")
        # нормализуем в Decimal
        amount_min = Decimal(str(m.get("limits", {}).get("amount", {}).get("min", 0))) if m.get("limits") else None
        cost_min = Decimal(str(m.get("limits", {}).get("cost", {}).get("min", 0))) if m.get("limits") else None
        p_amount = int(m.get("precision", {}).get("amount", 8))
        p_price = int(m.get("precision", {}).get("price", 8))
        return {
            "precision": {"amount": p_amount, "price": p_price},
            "limits": {"amount": {"min": amount_min}, "cost": {"min": cost_min}},
        }

    # --- interface ---
    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        ps = parse_symbol(symbol)
        ex_symbol = to_exchange_symbol(ps, self.exchange_id)
        now = now_ms()

        if self.dry_run:
            # dry-run: безопасный тикер, чтобы тесты проходили без сети
            p = Decimal("100")
            return TickerDTO(symbol=symbol, last=float(p), bid=float(p - Decimal("0.1")), ask=float(p + Decimal("0.1")), timestamp=now)

        try:
            self._ensure_exchange()
            t = await self._ex.fetch_ticker(ex_symbol)
            last = float(t.get("last") or t.get("close") or 0.0)
            bid = float(t.get("bid") or last or 0.0)
            ask = float(t.get("ask") or last or 0.0)
            ts = int(t.get("timestamp") or now)
            return TickerDTO(symbol=symbol, last=last, bid=bid, ask=ask, timestamp=ts)
        except ccxt.RateLimitExceeded as exc:  # type: ignore[attr-defined]
            raise TransientError(str(exc)) from exc
        except Exception as exc:
            raise TransientError(str(exc)) from exc

    async def create_market_buy_quote(self, symbol: str, *, amount_quote: Decimal) -> OrderDTO:
        """
        BUY QUOTE: покупаем на сумму в котируемой валюте (USDT).
        - переводим quote→base по ask
        - учитываем precision/limits
        - в dry_run не ходим в сеть
        """
        if amount_quote <= 0:
            raise ValidationError("amount_quote must be > 0")
        ps = parse_symbol(symbol)
        ex_symbol = to_exchange_symbol(ps, self.exchange_id)
        info = self._market_info(ex_symbol)

        t = await self.fetch_ticker(symbol)
        ask = Decimal(str(t.ask or t.last or 0))
        if ask <= 0:
            raise TransientError("ticker ask is not available")

        # сколько base можно купить на amount_quote
        raw_amount_base = amount_quote / ask

        # квантование до precision amount
        p_amount = int(info["precision"]["amount"])
        amount_base_q = _q(raw_amount_base, p_amount)

        # проверка минимального amount и минимальной cost
        min_amount = info["limits"]["amount"]["min"]
        if min_amount and amount_base_q < min_amount:
            raise ValidationError("calculated base amount is too small after rounding")

        min_cost = info["limits"]["cost"]["min"]
        if min_cost and amount_quote < min_cost:
            raise ValidationError("quote amount below minimum cost")

        client_id = make_client_order_id(self.exchange_id, f"{symbol}:buy")

        if self.dry_run:
            # эмулируем «мгновенное полное исполнение»
            filled = amount_base_q
            status = "closed"
            ts = now_ms()
            return OrderDTO(
                id=f"dry-{client_id}",
                client_order_id=client_id,
                symbol=symbol,
                side="buy",
                amount=float(amount_base_q),
                status=status,
                filled=float(filled),
                timestamp=ts,
            )

        try:
            self._ensure_exchange()
            # Многие биржи требуют amount в BASE, поэтому шлем amount_base_q
            order = await self._ex.create_order(ex_symbol, "market", "buy", float(amount_base_q), None, {"clientOrderId": client_id})
            return self._map_order(symbol, order, fallback_amount=float(amount_base_q), client_order_id=client_id)
        except ccxt.RateLimitExceeded as exc:  # type: ignore[attr-defined]
            raise TransientError(str(exc)) from exc
        except ccxt.InvalidOrder as exc:  # type: ignore[attr-defined]
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            raise TransientError(str(exc)) from exc

    async def create_market_sell_base(self, symbol: str, *, amount_base: Decimal) -> OrderDTO:
        """
        SELL BASE: продаём указанное количество базовой валюты.
        - квантование по precision
        - проверка минимального amount
        """
        if amount_base <= 0:
            raise ValidationError("amount_base must be > 0")
        ps = parse_symbol(symbol)
        ex_symbol = to_exchange_symbol(ps, self.exchange_id)
        info = self._market_info(ex_symbol)

        p_amount = int(info["precision"]["amount"])
        amount_base_q = _q(amount_base, p_amount)

        min_amount = info["limits"]["amount"]["min"]
        if min_amount and amount_base_q < min_amount:
            raise ValidationError("amount_base too small after rounding")

        client_id = make_client_order_id(self.exchange_id, f"{symbol}:sell")

        if self.dry_run:
            filled = amount_base_q
            status = "closed"
            ts = now_ms()
            return OrderDTO(
                id=f"dry-{client_id}",
                client_order_id=client_id,
                symbol=symbol,
                side="sell",
                amount=float(amount_base_q),
                status=status,
                filled=float(filled),
                timestamp=ts,
            )

        try:
            self._ensure_exchange()
            order = await self._ex.create_order(ex_symbol, "market", "sell", float(amount_base_q), None, {"clientOrderId": client_id})
            return self._map_order(symbol, order, fallback_amount=float(amount_base_q), client_order_id=client_id)
        except ccxt.RateLimitExceeded as exc:  # type: ignore[attr-defined]
            raise TransientError(str(exc)) from exc
        except ccxt.InvalidOrder as exc:  # type: ignore[attr-defined]
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            raise TransientError(str(exc)) from exc

    # --- mapping ---
    def _map_order(self, symbol: str, o: Dict[str, Any], *, fallback_amount: float, client_order_id: str) -> OrderDTO:
        """
        Приводим CCXT-ордер к нашему DTO, учитываем partial fills и комиссии, если ccxt их дал.
        (DTO оставляем прежним, чтобы не ломать код/тесты.)
        """
        status = str(o.get("status") or "open")
        filled = float(o.get("filled") or 0.0)
        amount = float(o.get("amount") or fallback_amount)
        ts = int(o.get("timestamp") or now_ms())
        oid = str(o.get("id") or client_order_id)
        side = str(o.get("side") or "buy")

        # Комиссию можем логировать, но в DTO её нет — не меняем интерфейс ради совместимости
        fee = o.get("fee") or {}
        if fee:
            try:
                fee_cost = float(fee.get("cost") or 0.0)
                fee_code = str(fee.get("currency") or "")
                self._log.info("order_fee_info", extra={"id": oid, "fee_cost": fee_cost, "fee_currency": fee_code})
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
