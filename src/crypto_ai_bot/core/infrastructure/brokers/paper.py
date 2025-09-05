from __future__ import annotations

import random
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
import uuid

from crypto_ai_bot.core.application.ports import (
    BalanceDTO,
    OrderDTO,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionDTO,
    TickerDTO,
)
from crypto_ai_bot.core.infrastructure.brokers.base import BaseBroker
#if your utils.decimal exposes dec()
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.trace import trace_context

_log = get_logger("infrastructure.brokers.paper")


class PaperBroker(BaseBroker):
    """
    Paper trading broker для симуляции торговли.

    Ключевые особенности:
    - Локальное хранение ордеров и балансов
    - Мгновенное исполнение market/limit ордеров
    - Эмуляция spread и slippage
    - Опциональная эмуляция частичных заполнений
    - Идемпотентность через client_order_id
    - Полная интеграция с trace_id

    Ограничения (согласно архитектуре):
    - Только SPOT торговля
    - Только LONG позиции (NO_SHORTS принцип)
    - Stop-Loss ордера не триггерятся автоматически (статичны)
    """

    def __init__(
        self,
        initial_balance_quote: Decimal = dec("10000.0"),
        initial_assets: Optional[dict[str, Decimal]] = None,
        slippage_pct: Decimal = dec("0.1"),
        spread_pct: Decimal = dec("0.05"),
        fee_pct: Decimal = dec("0.1"),
        partial_fill_chance: float = 0.0,
        price_volatility: Decimal = dec("0.5"),
    ):
        """
        Args:
            initial_balance_quote: Начальный баланс в USDT
            initial_assets: Начальные активы {currency: amount}
            slippage_pct: Процент slippage для market ордеров
            spread_pct: Процент bid/ask spread
            fee_pct: Процент торговой комиссии
            partial_fill_chance: Вероятность частичного заполнения (0-1)
            price_volatility: Волатильность цен для эмуляции (%)
        """
        super().__init__(exchange="paper", mode="paper")

        # Балансы (только spot)
        self.balances: dict[str, Decimal] = {
            "USDT": initial_balance_quote,
            "BTC": dec("0"),
            "ETH": dec("0"),
            "SOL": dec("0"),
        }
        if initial_assets:
            self.balances.update(initial_assets)

        # Хранилище ордеров с идемпотентностью
        self.orders: dict[str, OrderDTO] = {}  # by order_id
        self.client_orders: dict[str, str] = {}  # client_order_id -> order_id
        self.order_counter = 0

        # Позиции (spot only)
        self.positions: dict[str, PositionDTO] = {}

        # Параметры симуляции
        self.slippage_pct = slippage_pct
        self.spread_pct = spread_pct
        self.fee_pct = fee_pct
        self.partial_fill_chance = partial_fill_chance
        self.price_volatility = price_volatility

        # Кэш цен для реалистичной эмуляции
        self.price_cache: dict[str, Decimal] = {
            "BTC/USDT": dec("50000.0"),
            "ETH/USDT": dec("3000.0"),
            "SOL/USDT": dec("100.0"),
            "ADA/USDT": dec("0.5"),
            "DOT/USDT": dec("8.0"),
        }

        _log.info(
            "paper_broker_initialized",
            extra={
                "initial_balance_usdt": str(initial_balance_quote),
                "slippage_pct": str(slippage_pct),
                "spread_pct": str(spread_pct),
                "fee_pct": str(fee_pct),
                "partial_fill_chance": partial_fill_chance,
                "supported_symbols": list(self.price_cache.keys()),
            }
        )

    # ============= PRICE SIMULATION =============

    def _get_realistic_price(self, symbol: str) -> Decimal:
        """
        Получает реалистичную цену с эмуляцией волатильности.

        Использует базовую цену + случайные колебания в пределах volatility.
        """
        if symbol not in self.price_cache:
            # Дефолтная цена для неизвестных символов
            base_currency = symbol.split("/")[0]
            if "BTC" in base_currency:
                self.price_cache[symbol] = dec("50000.0")
            elif "ETH" in base_currency:
                self.price_cache[symbol] = dec("3000.0")
            else:
                self.price_cache[symbol] = dec("100.0")

        # Добавляем случайную вариацию в пределах volatility
        base_price = self.price_cache[symbol]
        volatility_range = self.price_volatility / 100  # Convert to decimal

        # Случайное изменение от -volatility до +volatility
        variation_factor = dec(str(1 - volatility_range + random.random() * 2 * volatility_range))
        realistic_price = base_price * variation_factor

        # Обновляем кэш для следующего запроса (имитация движения цены)
        self.price_cache[symbol] = realistic_price

        return realistic_price

    def _apply_slippage(self, price: Decimal, side: OrderSide) -> Decimal:
        """Применяет slippage к цене в зависимости от направления ордера."""
        slippage = price * self.slippage_pct / 100
        if side == OrderSide.BUY:
            return price + slippage  # Покупаем дороже
        else:
            return price - slippage  # Продаём дешевле

    def _calculate_trading_fee(self, amount: Decimal, price: Decimal, *, fee_currency: str) -> tuple[Decimal, str]:
        """Рассчитывает торговую комиссию в указанной валюте комиссии."""
        cost = amount * price
        fee = cost * self.fee_pct / 100
        return fee, fee_currency

    def _generate_unique_order_id(self) -> str:
        """Генерирует уникальный ID ордера."""
        self.order_counter += 1
        return f"paper_{self.order_counter}_{uuid.uuid4().hex[:8]}"

    def _check_idempotency(self, client_order_id: str) -> Optional[OrderDTO]:
        """
        Проверяет идемпотентность через client_order_id.

        Returns:
            Существующий ордер если найден, None если новый запрос.
        """
        if client_order_id in self.client_orders:
            order_id = self.client_orders[client_order_id]
            existing_order = self.orders.get(order_id)
            if existing_order:
                _log.debug(
                    "idempotent_order_found",
                    extra={
                        "client_order_id": client_order_id,
                        "existing_order_id": order_id,
                    }
                )
                return existing_order
        return None

    # ============= MARKET DATA =============

    async def _fetch_ticker_impl(self, symbol: str) -> TickerDTO:
        """Получает симулированный тикер с реалистичным spread."""
        with trace_context() as trace_id:
            price = self._get_realistic_price(symbol)
            spread_amount = price * self.spread_pct / 100

            ticker = TickerDTO(
                symbol=symbol,
                last=price,
                bid=price - spread_amount,
                ask=price + spread_amount,
                spread_pct=self.spread_pct,
                volume_24h=dec("1000000"),  # Фиктивный объём
                timestamp=datetime.now(timezone.utc)
            )

            _log.debug(
                "ticker_simulated",
                extra={
                    "symbol": symbol,
                    "price": str(price),
                    "bid": str(ticker.bid),
                    "ask": str(ticker.ask),
                    "trace_id": trace_id,
                }
            )

            return ticker

    async def _fetch_ohlcv_impl(
        self,
        symbol: str,
        timeframe: str,
        limit: int
    ) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]]:
        """Генерирует симулированные OHLCV данные."""
        result = []
        base_price = self._get_realistic_price(symbol)
        now = datetime.now(timezone.utc)

        # Интервалы в минутах
        timeframe_minutes = {
            '1m': 1, '5m': 5, '15m': 15, '30m': 30,
            '1h': 60, '4h': 240, '1d': 1440, '1w': 10080
        }
        minutes = timeframe_minutes.get(timeframe, 60)

        # Генерируем данные назад от текущего времени
        for i in range(limit):
            timestamp = datetime.fromtimestamp(
                now.timestamp() - minutes * 60 * i,
                tz=timezone.utc
            )

            # Генерируем OHLCV с небольшими вариациями
            price_variation = dec(str(0.98 + (i % 20) * 0.002))  # Больше разнообразия
            close = base_price * price_variation

            # Open с небольшим отклонением от close
            open_variation = dec(str(0.999 + random.random() * 0.002))
            open_price = close * open_variation

            # High и Low на основе open и close
            max_price = max(open_price, close)
            min_price = min(open_price, close)

            high = max_price * dec(str(1.001 + random.random() * 0.003))
            low = min_price * dec(str(0.997 + random.random() * 0.003))

            # Объём с вариацией
            volume = dec(str(10000 + random.random() * 15000))

            result.append((timestamp, open_price, high, low, close, volume))

        return list(reversed(result))  # Хронологический порядок

    # ============= ACCOUNT =============

    async def _fetch_balance_impl(self) -> dict[str, BalanceDTO]:
        """Получает симулированные балансы аккаунта."""
        result = {}
        for currency, amount in self.balances.items():
            # В paper режиме весь баланс считается свободным
            result[currency] = BalanceDTO(
                currency=currency,
                free=amount,
                used=dec("0"),  # Заблокированных средств нет
                total=amount
            )
        return result

    async def _fetch_position_impl(self, symbol: str) -> Optional[PositionDTO]:
        """Получает открытую позицию для символа (только LONG)."""
        return self.positions.get(symbol)

    # ============= ORDERS EXECUTION =============

    async def _create_market_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        client_order_id: str,
        trace_id: Optional[str]
    ) -> OrderDTO:
        """Создаёт и мгновенно исполняет market ордер."""
        # Проверка идемпотентности
        existing = self._check_idempotency(client_order_id)
        if existing:
            return existing

        # NO_SHORTS проверка: запрещаем short позиции
        if side == OrderSide.SELL:
            await self._validate_no_shorts_sell(symbol, amount)

        # Получаем цену с slippage
        current_price = self._get_realistic_price(symbol)
        execution_price = self._apply_slippage(current_price, side)

        # Парсим символ
        base_currency, quote_currency = symbol.split("/")

        # Эмуляция частичного заполнения
        filled_amount = amount
        if random.random() < self.partial_fill_chance:
            # Частичное заполнение от 50% до 99%
            fill_ratio = dec(str(0.5 + random.random() * 0.49))
            filled_amount = amount * fill_ratio

        # Рассчитываем комиссию за фактически исполненный объём
        fee, fee_currency = self._calculate_trading_fee(filled_amount, execution_price, fee_currency=quote_currency)

        # Проверяем балансы и обновляем их
        if side == OrderSide.BUY:
            actual_cost = filled_amount * execution_price
            required_quote = actual_cost + fee
            available_quote = self.balances.get(quote_currency, dec("0"))
            if available_quote < required_quote:
                raise ValueError(
                    f"Insufficient {quote_currency} balance: need {required_quote}, have {available_quote}"
                )
            self.balances[quote_currency] = available_quote - required_quote
            self.balances[base_currency] = self.balances.get(base_currency, dec("0")) + filled_amount
        else:  # SELL
            available_base = self.balances.get(base_currency, dec("0"))
            if available_base < filled_amount:
                raise ValueError(
                    f"Insufficient {base_currency} balance: need {filled_amount}, have {available_base}"
                )
            proceeds = filled_amount * execution_price
            self.balances[base_currency] = available_base - filled_amount
            self.balances[quote_currency] = self.balances.get(quote_currency, dec("0")) + (proceeds - fee)

        # Создаём ордер
        order_id = self._generate_unique_order_id()
        order_status = OrderStatus.CLOSED if filled_amount == amount else OrderStatus.PARTIALLY_FILLED

        info = {
            "slippage_applied": str(abs(execution_price - current_price)),
            "simulation": "paper_trading",
        }
        if trace_id:
            info["trace_id"] = trace_id

        order = OrderDTO(
            id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            type=OrderType.MARKET,
            status=order_status,
            price=execution_price,
            amount=amount,
            filled=filled_amount,
            remaining=amount - filled_amount,
            fee=fee,
            fee_currency=fee_currency,
            timestamp=datetime.now(timezone.utc),
            info=info,
        )

        # Сохраняем ордер
        self.orders[order_id] = order
        self.client_orders[client_order_id] = order_id

        _log.info(
            "paper_market_order_executed",
            extra={
                "order_id": order_id,
                "client_order_id": client_order_id,
                "symbol": symbol,
                "side": side.value,
                "amount": str(amount),
                "filled": str(filled_amount),
                "execution_price": str(execution_price),
                "fee": str(order.fee),
                "status": order_status.value,
                "trace_id": trace_id or "none",
            }
        )

        return order

    async def _validate_no_shorts_sell(self, symbol: str, amount: Decimal) -> None:
        """
        Проверяет NO_SHORTS ограничение для продаж.

        Разрешает продавать только то, что есть в наличии.
        """
        base_currency = symbol.split("/")[0]
        available = self.balances.get(base_currency, dec("0"))

        if available < amount:
            raise ValueError(
                f"NO_SHORTS violation: cannot sell {amount} {base_currency}, "
                f"only {available} available. Short positions are forbidden."
            )

    async def _create_limit_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
        client_order_id: str,
        trace_id: Optional[str]
    ) -> OrderDTO:
        """Создаёт limit ордер (в paper режиме мгновенно исполняется с обновлением балансов)."""
        # Проверка идемпотентности
        existing = self._check_idempotency(client_order_id)
        if existing:
            return existing

        # NO_SHORTS проверка
        if side == OrderSide.SELL:
            await self._validate_no_shorts_sell(symbol, amount)

        base_currency, quote_currency = symbol.split("/")
        fee, fee_currency = self._calculate_trading_fee(amount, price, fee_currency=quote_currency)

        # Проверяем балансы и применяем изменения (как при мгновенном исполнении)
        if side == OrderSide.BUY:
            required = amount * price + fee
            available = self.balances.get(quote_currency, dec("0"))
            if available < required:
                raise ValueError(f"Insufficient {quote_currency} balance: need {required}, have {available}")
            self.balances[quote_currency] = available - required
            self.balances[base_currency] = self.balances.get(base_currency, dec("0")) + amount
        else:
            available_base = self.balances.get(base_currency, dec("0"))
            if available_base < amount:
                raise ValueError(f"Insufficient {base_currency} balance: need {amount}, have {available_base}")
            proceeds = amount * price
            self.balances[base_currency] = available_base - amount
            self.balances[quote_currency] = self.balances.get(quote_currency, dec("0")) + (proceeds - fee)

        info = {"simulation": "paper_trading", "note": "limit_order_instant_fill"}
        if trace_id:
            info["trace_id"] = trace_id

        order_id = self._generate_unique_order_id()
        order = OrderDTO(
            id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            type=OrderType.LIMIT,
            status=OrderStatus.CLOSED,
            price=price,
            amount=amount,
            filled=amount,
            remaining=dec("0"),
            fee=fee,
            fee_currency=fee_currency,
            timestamp=datetime.now(timezone.utc),
            info=info,
        )

        # Сохраняем ордер
        self.orders[order_id] = order
        self.client_orders[client_order_id] = order_id

        _log.info(
            "paper_limit_order_executed",
            extra={
                "order_id": order_id,
                "client_order_id": client_order_id,
                "symbol": symbol,
                "side": side.value,
                "amount": str(amount),
                "price": str(price),
                "trace_id": trace_id or "none",
            }
        )

        return order

    async def _create_stop_loss_order_impl(
        self,
        symbol: str,
        amount: Decimal,
        stop_price: Decimal,
        client_order_id: str,
        trace_id: Optional[str]
    ) -> OrderDTO:
        """
        Создаёт stop-loss ордер.

        ВАЖНО: В paper режиме stop-loss ордера НЕ триггерятся автоматически!
        Они остаются в статусе OPEN для эмуляции pending ордеров.
        """
        # Проверка идемпотентности
        existing = self._check_idempotency(client_order_id)
        if existing:
            return existing

        # NO_SHORTS проверка
        await self._validate_no_shorts_sell(symbol, amount)

        info = {
            "stop_price": str(stop_price),
            "simulation": "paper_trading",
            "note": "stop_loss_not_triggered_automatically",
        }
        if trace_id:
            info["trace_id"] = trace_id

        order_id = self._generate_unique_order_id()
        order = OrderDTO(
            id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=OrderSide.SELL,  # Stop-loss всегда продажа
            type=OrderType.STOP_LOSS,
            status=OrderStatus.OPEN,  # Остаётся открытым
            price=stop_price,
            amount=amount,
            filled=dec("0"),
            remaining=amount,
            fee=dec("0"),  # Комиссия только при исполнении
            fee_currency=symbol.split("/")[1],
            timestamp=datetime.now(timezone.utc),
            info=info,
        )

        # Сохраняем ордер
        self.orders[order_id] = order
        self.client_orders[client_order_id] = order_id

        _log.info(
            "paper_stop_loss_created",
            extra={
                "order_id": order_id,
                "client_order_id": client_order_id,
                "symbol": symbol,
                "amount": str(amount),
                "stop_price": str(stop_price),
                "trace_id": trace_id or "none",
                "warning": "stop_loss_not_triggered_automatically",
            }
        )

        return order

    # ============= ORDER MANAGEMENT =============

    async def _cancel_order_impl(self, order_id: str, symbol: str) -> OrderDTO:
        """Отменяет ордер."""
        if order_id in self.orders:
            order = self.orders[order_id]
            if order.status == OrderStatus.OPEN:
                order.status = OrderStatus.CANCELED
                _log.info(
                    "paper_order_canceled",
                    extra={
                        "order_id": order_id,
                        "symbol": symbol,
                        "client_order_id": order.client_order_id,
                    }
                )
            return order

        # Возвращаем dummy отменённый ордер если не найден
        _log.warning("cancel_order_not_found", extra={"order_id": order_id, "symbol": symbol})
        return OrderDTO(
            id=order_id,
            client_order_id="unknown",
            symbol=symbol,
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            status=OrderStatus.CANCELED,
            price=dec("0"),
            amount=dec("0"),
            filled=dec("0"),
            remaining=dec("0"),
            fee=dec("0"),
            fee_currency="USDT",
            timestamp=datetime.now(timezone.utc),
            info={"simulation": "paper_trading", "note": "order_not_found"}
        )

    async def _fetch_order_impl(self, order_id: str, symbol: str) -> OrderDTO:
        """Получает ордер по ID."""
        if order_id in self.orders:
            return self.orders[order_id]

        # Возвращаем dummy закрытый ордер
        _log.debug("fetch_order_not_found", extra={"order_id": order_id, "symbol": symbol})
        return OrderDTO(
            id=order_id,
            client_order_id="unknown",
            symbol=symbol,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            status=OrderStatus.CLOSED,
            price=self._get_realistic_price(symbol),
            amount=dec("0"),
            filled=dec("0"),
            remaining=dec("0"),
            fee=dec("0"),
            fee_currency="USDT",
            timestamp=datetime.now(timezone.utc),
            info={"simulation": "paper_trading", "note": "order_not_found"}
        )

    async def _fetch_open_orders_impl(self, symbol: Optional[str]) -> list[OrderDTO]:
        """Получает открытые ордера (включая PARTIALLY_FILLED)."""
        result = []
        for order in self.orders.values():
            if order.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED):
                if symbol is None or order.symbol == symbol:
                    result.append(order)

        _log.debug(
            "fetch_open_orders",
            extra={
                "symbol": symbol or "all",
                "count": len(result),
            }
        )
        return result

    async def _fetch_closed_orders_impl(
        self,
        symbol: str,
        since: Optional[datetime],
        limit: int
    ) -> list[OrderDTO]:
        """Получает закрытые ордера."""
        result = []
        for order in self.orders.values():
            if (order.symbol == symbol and
                order.status in (OrderStatus.CLOSED, OrderStatus.CANCELED)):
                if since is None or order.timestamp >= since:
                    result.append(order)

        # Сортируем по времени (новые сначала) и ограничиваем
        result.sort(key=lambda x: x.timestamp, reverse=True)
        return result[:limit]

    # ============= UTILITY METHODS =============

    def get_simulation_stats(self) -> dict:
        """Возвращает статистику симуляции для отладки."""
        total_orders = len(self.orders)
        open_orders = len([o for o in self.orders.values() if o.status == OrderStatus.OPEN])
        closed_orders = len([o for o in self.orders.values() if o.status == OrderStatus.CLOSED])

        return {
            "total_orders": total_orders,
            "open_orders": open_orders,
            "closed_orders": closed_orders,
            "balances": {k: str(v) for k, v in self.balances.items()},
            "price_cache": {k: str(v) for k, v in self.price_cache.items()},
        }
