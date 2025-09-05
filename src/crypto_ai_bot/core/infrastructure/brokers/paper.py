"""
Paper trading broker implementation.
Emulator for testing without real money.
"""
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
    PositionSide,
    TickerDTO,
)
from crypto_ai_bot.core.infrastructure.brokers.base import BaseBroker
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

logger = get_logger(__name__)


class PaperBroker(BaseBroker):
    """
    Paper trading broker for simulation.
    
    Features:
    - Local storage of orders and balances
    - Instant market order execution
    - Spread and slippage simulation
    - Optional partial fill simulation
    """
    
    def __init__(
        self,
        initial_balance_quote: Decimal = dec("10000.0"),
        initial_assets: Optional[dict[str, Decimal]] = None,
        slippage_pct: Decimal = dec("0.1"),
        spread_pct: Decimal = dec("0.05"),
        fee_pct: Decimal = dec("0.1"),
        partial_fill_chance: float = 0.0,
    ):
        """
        Args:
            initial_balance_quote: Initial balance in USDT
            initial_assets: Initial assets {symbol: amount}
            slippage_pct: Slippage percentage for market orders
            spread_pct: Bid/ask spread percentage
            fee_pct: Trading fee percentage
            partial_fill_chance: Chance of partial fill (0-1)
        """
        super().__init__(exchange="paper", mode="paper")
        
        # Balances
        self.balances: dict[str, Decimal] = {
            "USDT": initial_balance_quote,
            "BTC": dec("0"),
            "ETH": dec("0"),
        }
        if initial_assets:
            self.balances.update(initial_assets)
        
        # Orders storage
        self.orders: dict[str, OrderDTO] = {}
        self.order_counter = 0
        
        # Positions storage
        self.positions: dict[str, PositionDTO] = {}
        
        # Simulation parameters
        self.slippage_pct = slippage_pct
        self.spread_pct = spread_pct
        self.fee_pct = fee_pct
        self.partial_fill_chance = partial_fill_chance
        
        # Price cache for simulation
        self.price_cache: dict[str, Decimal] = {
            "BTC/USDT": dec("50000.0"),
            "ETH/USDT": dec("3000.0"),
            "SOL/USDT": dec("100.0"),
        }
        
        logger.info("Paper broker initialized", extra={
            "initial_balance": str(initial_balance_quote),
            "slippage_pct": str(slippage_pct),
            "spread_pct": str(spread_pct),
            "fee_pct": str(fee_pct),
        })
    
    # ============= HELPERS =============
    
    def _get_price(self, symbol: str) -> Decimal:
        """Get simulated price for symbol"""
        if symbol not in self.price_cache:
            # Default price for unknown symbols
            self.price_cache[symbol] = dec("100.0")
        
        # Add small random variation (±0.5%)
        base_price = self.price_cache[symbol]
        variation = dec(str(0.995 + random.random() * 0.01))
        return base_price * variation
    
    def _apply_slippage(self, price: Decimal, side: OrderSide) -> Decimal:
        """Apply slippage to price based on order side"""
        slippage = price * self.slippage_pct / 100
        if side == OrderSide.BUY:
            return price + slippage  # Buy at higher price
        else:
            return price - slippage  # Sell at lower price
    
    def _calculate_fee(self, amount: Decimal, price: Decimal) -> tuple[Decimal, str]:
        """Calculate trading fee"""
        cost = amount * price
        fee = cost * self.fee_pct / 100
        return fee, "USDT"
    
    def _generate_order_id(self) -> str:
        """Generate unique order ID"""
        self.order_counter += 1
        return f"paper_{self.order_counter}_{uuid.uuid4().hex[:8]}"
    
    # ============= MARKET DATA =============
    
    async def _fetch_ticker_impl(self, symbol: str) -> TickerDTO:
        """Get simulated ticker"""
        price = self._get_price(symbol)
        spread = price * self.spread_pct / 100
        
        return TickerDTO(
            symbol=symbol,
            last=price,
            bid=price - spread,
            ask=price + spread,
            spread_pct=self.spread_pct,
            volume_24h=dec("1000000"),
            timestamp=datetime.now(timezone.utc)
        )
    
    async def _fetch_ohlcv_impl(
        self,
        symbol: str,
        timeframe: str,
        limit: int
    ) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]]:
        """Get simulated OHLCV data"""
        result = []
        base_price = self._get_price(symbol)
        now = datetime.now(timezone.utc)
        
        # Generate data backwards from now
        for i in range(limit):
            # Time offset based on timeframe
            minutes_offset = {
                '1m': 1, '5m': 5, '15m': 15, '30m': 30,
                '1h': 60, '4h': 240, '1d': 1440, '1w': 10080
            }.get(timeframe, 60) * i
            
            timestamp = datetime.fromtimestamp(
                now.timestamp() - minutes_offset * 60,
                tz=timezone.utc
            )
            
            # Generate OHLCV with small variations
            variation = dec(str(0.98 + (i % 10) * 0.004))
            close = base_price * variation
            open_price = close * dec(str(0.999 + random.random() * 0.002))
            high = max(open_price, close) * dec(str(1.001 + random.random() * 0.002))
            low = min(open_price, close) * dec(str(0.997 + random.random() * 0.002))
            volume = dec(str(10000 + random.random() * 5000))
            
            result.append((timestamp, open_price, high, low, close, volume))
        
        return list(reversed(result))
    
    # ============= ACCOUNT =============
    
    async def _fetch_balance_impl(self) -> dict[str, BalanceDTO]:
        """Get account balances"""
        result = {}
        for currency, amount in self.balances.items():
            result[currency] = BalanceDTO(
                currency=currency,
                free=amount,
                used=dec("0"),
                total=amount
            )
        return result
    
    async def _fetch_position_impl(self, symbol: str) -> Optional[PositionDTO]:
        """Get open position for symbol"""
        return self.positions.get(symbol)
    
    # ============= ORDERS =============
    
    async def _create_market_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        client_order_id: str,
        trace_id: str
    ) -> OrderDTO:
        """Create and execute market order"""
        # Get current price with slippage
        price = self._get_price(symbol)
        exec_price = self._apply_slippage(price, side)
        
        # Parse symbol
        base, quote = symbol.split("/")
        
        # Calculate cost and fee
        cost = amount * exec_price
        fee, fee_currency = self._calculate_fee(amount, exec_price)
        
        # Check balances
        if side == OrderSide.BUY:
            required = cost + fee
            if self.balances.get(quote, dec("0")) < required:
                raise ValueError(f"Insufficient {quote} balance: need {required}")
        else:
            if self.balances.get(base, dec("0")) < amount:
                raise ValueError(f"Insufficient {base} balance: need {amount}")
        
        # Simulate partial fill
        filled = amount
        if random.random() < self.partial_fill_chance:
            filled = amount * dec(str(0.5 + random.random() * 0.5))
        
        # Update balances
        if side == OrderSide.BUY:
            self.balances[quote] -= (filled * exec_price + fee)
            self.balances[base] = self.balances.get(base, dec("0")) + filled
        else:
            self.balances[base] -= filled
            self.balances[quote] = self.balances.get(quote, dec("0")) + (filled * exec_price - fee)
        
        # Create order
        order = OrderDTO(
            id=self._generate_order_id(),
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            type=OrderType.MARKET,
            status=OrderStatus.CLOSED if filled == amount else OrderStatus.PARTIALLY_FILLED,
            price=exec_price,
            amount=amount,
            filled=filled,
            remaining=amount - filled,
            fee=fee,
            fee_currency=fee_currency,
            timestamp=datetime.now(timezone.utc),
            info={"trace_id": trace_id}
        )
        
        self.orders[order.id] = order
        
        logger.info("Paper order executed", extra={
            "order_id": order.id,
            "symbol": symbol,
            "side": side.value,
            "amount": str(amount),
            "filled": str(filled),
            "price": str(exec_price),
            "trace_id": trace_id,
        })
        
        return order
    
    async def _create_limit_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
        client_order_id: str,
        trace_id: str
    ) -> OrderDTO:
        """Create limit order (instantly filled in paper mode)"""
        # In paper mode, limit orders are instantly filled at requested price
        order = OrderDTO(
            id=self._generate_order_id(),
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            type=OrderType.LIMIT,
            status=OrderStatus.CLOSED,
            price=price,
            amount=amount,
            filled=amount,
            remaining=dec("0"),
            fee=self._calculate_fee(amount, price)[0],
            fee_currency="USDT",
            timestamp=datetime.now(timezone.utc),
            info={"trace_id": trace_id}
        )
        
        self.orders[order.id] = order
        return order
    
    async def _create_stop_loss_order_impl(
        self,
        symbol: str,
        amount: Decimal,
        stop_price: Decimal,
        client_order_id: str,
        trace_id: Optional[str]
    ) -> OrderDTO:
        """Create stop-loss order (not triggered in paper mode)"""
        info = {"stop_price": str(stop_price)}
        if trace_id:
            info["trace_id"] = trace_id
            
        order = OrderDTO(
            id=self._generate_order_id(),
            client_order_id=client_order_id,
            symbol=symbol,
            side=OrderSide.SELL,
            type=OrderType.STOP_LOSS,
            status=OrderStatus.OPEN,
            price=stop_price,
            amount=amount,
            filled=dec("0"),
            remaining=amount,
            fee=dec("0"),
            fee_currency=symbol.split("/")[1],  # Use quote currency
            timestamp=datetime.now(timezone.utc),
            info=info
        )
        
        self.orders[order.id] = order
        return order
    
    async def _cancel_order_impl(
        self,
        order_id: str,
        symbol: str
    ) -> OrderDTO:
        """Cancel order"""
        if order_id in self.orders:
            order = self.orders[order_id]
            order.status = OrderStatus.CANCELED
            return order
        
        # Return dummy canceled order
        return OrderDTO(
            id=order_id,
            client_order_id="",
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
            info={}
        )
    
    async def _fetch_order_impl(
        self,
        order_id: str,
        symbol: str
    ) -> OrderDTO:
        """Get order by ID"""
        if order_id in self.orders:
            return self.orders[order_id]
        
        # Return dummy closed order
        return OrderDTO(
            id=order_id,
            client_order_id="",
            symbol=symbol,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            status=OrderStatus.CLOSED,
            price=self._get_price(symbol),
            amount=dec("0"),
            filled=dec("0"),
            remaining=dec("0"),
            fee=dec("0"),
            fee_currency="USDT",
            timestamp=datetime.now(timezone.utc),
            info={}
        )
    
    async def _fetch_open_orders_impl(
        self,
        symbol: Optional[str]
    ) -> list[OrderDTO]:
        """Get open orders"""
        result = []
        for order in self.orders.values():
            if order.status == OrderStatus.OPEN:
                if symbol is None or order.symbol == symbol:
                    result.append(order)
        return result
    
    async def _fetch_closed_orders_impl(
        self,
        symbol: str,
        since: Optional[datetime],
        limit: int
    ) -> list[OrderDTO]:
        """Get closed orders"""
        result = []
        for order in self.orders.values():
            if order.symbol == symbol and order.status == OrderStatus.CLOSED:
                if since is None or order.timestamp >= since:
                    result.append(order)
        
        # Sort by timestamp and limit
        result.sort(key=lambda x: x.timestamp, reverse=True)
        return result[:limit]