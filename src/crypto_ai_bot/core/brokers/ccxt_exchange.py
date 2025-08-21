from __future__ import annotations
import asyncio
from typing import Any
from dataclasses import dataclass

from crypto_ai_bot.core.brokers.base import IBroker, TickerDTO, BalanceDTO, OrderDTO
from crypto_ai_bot.core.brokers.symbols import to_exchange_symbol
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.retry import retry_async
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils.ids import make_client_order_id


@dataclass(slots=True)
class _Placed:
    id: str
    client_order_id: str
    symbol: str
    side: str
    type: str
    amount: float
    price: float
    status: str
    ts_ms: int | None = None


class CCXTBroker(IBroker):
    """Реализация IBroker через библиотеку ccxt (используем sync API в threadpool).
    Минимизируем знание про конкретные биржи: лишь нормализация символа и client order id.
    """

    def __init__(self, settings: Any) -> None:
        self._log = get_logger("broker.ccxt")
        self.settings = settings
        try:
            import ccxt  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("ccxt не установлен. Установите пакет `ccxt`.") from e

        ex_name = (settings.EXCHANGE or "gateio").replace(".", "")
        if not hasattr(ccxt, ex_name):
            raise RuntimeError(f"ccxt не знает биржу '{settings.EXCHANGE}'")
        ex_cls = getattr(ccxt, ex_name)
        kwargs: dict[str, Any] = {}
        if settings.MODE == "live":
            kwargs["apiKey"] = settings.API_KEY
            kwargs["secret"] = settings.API_SECRET
            if getattr(settings, "API_PASSWORD", None):
                kwargs["password"] = settings.API_PASSWORD
        self._ex = ex_cls(kwargs) if kwargs else ex_cls()
        # circuit breaker для нестабильных вызовов
        self._cb = CircuitBreaker(name="ccxt", timeout=10.0, threshold=3)

    # --- helpers ---
    async def _to_thread(self, fn, *a, **kw):
        return await asyncio.to_thread(fn, *a, **kw)

    # --- server time (для health) ---
    def fetch_server_time_ms(self) -> int:
        try:
            # не все биржи поддерживают, fallback на локальные миллисекунды ccxt
            if hasattr(self._ex, "fetch_time"):
                ms = self._ex.fetch_time()
                if isinstance(ms, (int, float)):
                    return int(ms)
            return int(self._ex.milliseconds())
        except Exception:
            return 0

    # --- IBroker methods ---
    @retry_async(attempts=3, backoff_base=0.2, backoff_factor=2.0)
    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        ex_symbol = to_exchange_symbol(self.settings.EXCHANGE, symbol)
        @self._cb
        def _call():
            return self._ex.fetch_ticker(ex_symbol)
        data = await self._to_thread(_call)
        last = data.get("last") or data.get("close")
        if last is None:
            raise RuntimeError(f"fetch_ticker: биржа не вернула last/close для {ex_symbol}")
        ts = data.get("timestamp") or data.get("datetime") or None
        return TickerDTO(symbol=symbol, last=float(last), ts_ms=int(ts) if ts else None)

    @retry_async(attempts=3, backoff_base=0.2, backoff_factor=2.0)
    async def fetch_balance(self) -> BalanceDTO:
        @self._cb
        def _call():
            return self._ex.fetch_balance()
        data = await self._to_thread(_call)
        free = {k: float(v) for k, v in (data.get("free") or {}).items()}
        total = {k: float(v) for k, v in (data.get("total") or {}).items()}
        return BalanceDTO(free=free, total=total)

    # BUY за фиксированную сумму QUOTE
    @retry_async(attempts=3, backoff_base=0.25, backoff_factor=2.0)
    async def create_market_buy_quote(self, *, symbol: str, quote_amount: float, idempotency_key: str) -> OrderDTO:
        # Преобразуем в базовый объём через текущий last, если у биржи нет параметра 'cost'
        ticker = await self.fetch_ticker(symbol)
        base_amount = float(quote_amount) / max(ticker.last, 1e-12)
        return await self._place_market(symbol=symbol, side="buy", base_amount=base_amount, idempotency_key=idempotency_key)

    # SELL фиксированного количества BASE
    @retry_async(attempts=3, backoff_base=0.25, backoff_factor=2.0)
    async def create_market_sell_base(self, *, symbol: str, base_amount: float, idempotency_key: str) -> OrderDTO:
        return await self._place_market(symbol=symbol, side="sell", base_amount=base_amount, idempotency_key=idempotency_key)

    # --- internal place market ---
    async def _place_market(self, *, symbol: str, side: str, base_amount: float, idempotency_key: str) -> OrderDTO:
        ex_symbol = to_exchange_symbol(self.settings.EXCHANGE, symbol)
        client_id = make_client_order_id(self.settings.EXCHANGE, idempotency_key)
        params: dict[str, Any] = {}
        # Биржевые особенности: Gate.io ожидает 'text' для client id
        if "gate" in self.settings.EXCHANGE:
            params["text"] = client_id
        else:
            params["clientOrderId"] = client_id

        @self._cb
        def _call():
            # Большинство бирж ccxt требует 'amount' для market-ордеров
            return self._ex.create_order(ex_symbol, "market", side, amount=base_amount, price=None, params=params)

        data = await self._to_thread(_call)
        placed = self._map_order(data, symbol, client_id)
        return OrderDTO(
            id=placed.id,
            client_order_id=placed.client_order_id,
            symbol=placed.symbol,
            side=placed.side,
            type=placed.type,
            amount=placed.amount,
            price=placed.price,
            status=placed.status,
        )

    # --- mapping ---
    def _map_order(self, raw: dict[str, Any], symbol_norm: str, client_id: str) -> _Placed:
        oid = str(raw.get("id") or raw.get("order") or client_id)
        filled = float(raw.get("filled") or raw.get("amount") or 0.0)
        price = float(raw.get("average") or raw.get("price") or 0.0)
        status = str(raw.get("status") or "open")
        ts = raw.get("timestamp")
        return _Placed(
            id=oid,
            client_order_id=client_id,
            symbol=symbol_norm,
            side=str(raw.get("side") or "buy"),
            type=str(raw.get("type") or "market"),
            amount=filled,
            price=price,
            status=status,
            ts_ms=int(ts) if ts else None,
        )
