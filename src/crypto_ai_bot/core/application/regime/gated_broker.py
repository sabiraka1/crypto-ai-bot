"""Gated broker for regime-based trading control.

Located in application/regime layer - filters trading operations based on market regime.
Implements BrokerPort interface with regime-aware restrictions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from crypto_ai_bot.core.application.ports import (
    BrokerPort,
    OrderDTO,
    OrderSide,
    PositionDTO,
    TickerDTO,
    BalanceDTO,
)
from crypto_ai_bot.core.application.events_topics import EventTopics
from crypto_ai_bot.core.domain.macro.regime_detector import RegimeDetector
from crypto_ai_bot.core.domain.macro.types import RegimeState
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.trace import generate_trace_id

_log = get_logger(__name__)


# ============== Configuration ==============

@dataclass(frozen=True)
class RegimePolicy:
    """Policy for regime-based trading restrictions."""

    # Block new long positions in risk_off regime
    block_longs_on_risk_off: bool = True

    # Block new long positions in neutral regime
    block_longs_on_neutral: bool = True

    # Allow closing positions (sells) even in risk_off
    allow_exits_when_restricted: bool = True

    # Reduce position size in risk_small regime
    reduce_size_on_risk_small: bool = True

    # Size reduction factor for risk_small (0.5 = 50% of normal)
    risk_small_size_factor: float = 0.5

    # Log all blocked operations
    log_blocked_operations: bool = True

    # Emit events for blocked/reduced operations
    emit_blocked_events: bool = True


# ============== Exceptions ==============

class RegimeBlockedException(Exception):
    """Exception raised when operation is blocked by regime."""

    def __init__(
        self,
        regime: RegimeState,
        operation: str,
        symbol: str,
        reason: str,
        trace_id: Optional[str] = None,
    ):
        self.regime = regime
        self.operation = operation
        self.symbol = symbol
        self.reason = reason
        self.trace_id = trace_id or generate_trace_id()

        super().__init__(
            f"Operation blocked by regime: {regime}. "
            f"Operation: {operation}, Symbol: {symbol}, Reason: {reason}"
        )


# ============== Gated Broker ==============

class GatedBroker(BrokerPort):
    """
    Broker wrapper that enforces regime-based trading restrictions.

    Filters trading operations based on current market regime:
    - risk_on: Full trading allowed
    - risk_small: Reduced position sizes
    - neutral: Only exits allowed (no new entries)
    - risk_off: All new positions blocked
    """

    def __init__(
        self,
        inner: BrokerPort,
        regime_detector: Optional[RegimeDetector] = None,
        policy: Optional[RegimePolicy] = None,
        event_bus: Optional[Any] = None,
    ):
        """
        Initialize gated broker.

        Args:
            inner: Underlying broker implementation
            regime_detector: Regime detector for market state
            policy: Trading restriction policy
            event_bus: Optional event bus for notifications
        """
        self._inner = inner
        self._regime = regime_detector
        self._policy = policy or RegimePolicy()
        self._event_bus = event_bus

        # Statistics
        self._stats = {
            "operations_allowed": 0,
            "operations_blocked": 0,
            "operations_reduced": 0,
        }

    # ============== Pass-through Methods ==============

    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        """Fetch ticker - always allowed."""
        return await self._inner.fetch_ticker(symbol)

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]]:
        """Fetch OHLCV - always allowed."""
        return await self._inner.fetch_ohlcv(symbol, timeframe, limit)

    async def fetch_balance(self) -> dict[str, BalanceDTO]:
        """Fetch balance - always allowed."""
        return await self._inner.fetch_balance()

    async def fetch_position(self, symbol: str) -> Optional[PositionDTO]:
        """Fetch position - always allowed."""
        return await self._inner.fetch_position(symbol)

    async def fetch_order(self, order_id: str, symbol: str) -> OrderDTO:
        """Fetch order - always allowed."""
        return await self._inner.fetch_order(order_id, symbol)

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> list[OrderDTO]:
        """Fetch open orders - always allowed."""
        return await self._inner.fetch_open_orders(symbol)

    async def fetch_closed_orders(
        self,
        symbol: str,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[OrderDTO]:
        """Fetch closed orders - always allowed."""
        return await self._inner.fetch_closed_orders(symbol, since, limit)

    async def cancel_order(self, order_id: str, symbol: str) -> OrderDTO:
        """Cancel order - always allowed."""
        return await self._inner.cancel_order(order_id, symbol)

    # ============== Regime-Filtered Methods ==============

    async def create_market_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        client_order_id: str,
    ) -> OrderDTO:
        """
        Create market order with regime filtering.

        Buy orders may be blocked or reduced based on regime.
        Sell orders are typically allowed (for exits).
        """
        trace_id = generate_trace_id()

        # Check if this is a buy order (new position)
        if side == OrderSide.BUY:
            # Apply regime filtering for buys
            amount = await self._filter_buy_order(
                symbol=symbol,
                amount=amount,
                trace_id=trace_id,
            )

        # Sells are typically allowed (exits)
        elif side == OrderSide.SELL and not self._policy.allow_exits_when_restricted:
            # Check if sells should also be restricted
            await self._check_regime_for_sells(symbol, trace_id)

        # Execute the order
        self._stats["operations_allowed"] += 1
        return await self._inner.create_market_order(
            symbol=symbol,
            side=side,
            amount=amount,
            client_order_id=client_order_id,
        )

    async def create_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
        client_order_id: str,
    ) -> OrderDTO:
        """
        Create limit order with regime filtering.

        Similar to market orders, buys may be blocked/reduced.
        """
        trace_id = generate_trace_id()

        # Check if this is a buy order
        if side == OrderSide.BUY:
            # Apply regime filtering for buys
            amount = await self._filter_buy_order(
                symbol=symbol,
                amount=amount,
                trace_id=trace_id,
            )

        # Sells are typically allowed
        elif side == OrderSide.SELL and not self._policy.allow_exits_when_restricted:
            await self._check_regime_for_sells(symbol, trace_id)

        # Execute the order
        self._stats["operations_allowed"] += 1
        return await self._inner.create_limit_order(
            symbol=symbol,
            side=side,
            amount=amount,
            price=price,
            client_order_id=client_order_id,
        )

    async def create_stop_loss_order(
        self,
        symbol: str,
        amount: Decimal,
        stop_price: Decimal,
        client_order_id: str,
    ) -> OrderDTO:
        """
        Create stop-loss order - always allowed.

        Stop-loss orders are protective exits and should never be blocked.
        """
        return await self._inner.create_stop_loss_order(
            symbol=symbol,
            amount=amount,
            stop_price=stop_price,
            client_order_id=client_order_id,
        )

    # ============== Private Methods ==============

    async def _get_current_regime(self) -> RegimeState:
        """Get current market regime."""
        if not self._regime:
            return RegimeState.RISK_ON  # Default if no detector

        return await self._regime.get_regime()

    async def _filter_buy_order(
        self,
        symbol: str,
        amount: Decimal,
        trace_id: str,
    ) -> Decimal:
        """
        Filter buy order based on regime.

        Returns adjusted amount (may be 0 if blocked).
        Raises RegimeBlockedException if operation is blocked.
        """
        regime = await self._get_current_regime()

        # Log regime check
        _log.info(
            "regime_check_for_buy",
            extra={
                "symbol": symbol,
                "regime": regime.value,
                "amount": str(amount),
                "trace_id": trace_id,
            },
        )

        # Check risk_off regime
        if regime == RegimeState.RISK_OFF and self._policy.block_longs_on_risk_off:
            self._handle_blocked_operation(
                regime=regime,
                operation="buy",
                symbol=symbol,
                reason="New long positions blocked in risk_off regime",
                trace_id=trace_id,
            )

            raise RegimeBlockedException(
                regime=regime,
                operation="buy",
                symbol=symbol,
                reason="risk_off regime blocks new longs",
                trace_id=trace_id,
            )

        # Check neutral regime
        if regime == RegimeState.NEUTRAL and self._policy.block_longs_on_neutral:
            self._handle_blocked_operation(
                regime=regime,
                operation="buy",
                symbol=symbol,
                reason="New long positions blocked in neutral regime",
                trace_id=trace_id,
            )

            raise RegimeBlockedException(
                regime=regime,
                operation="buy",
                symbol=symbol,
                reason="neutral regime blocks new longs",
                trace_id=trace_id,
            )

        # Check risk_small regime - reduce position size
        if regime == RegimeState.RISK_SMALL and self._policy.reduce_size_on_risk_small:
            original_amount = amount
            amount = amount * Decimal(str(self._policy.risk_small_size_factor))

            self._stats["operations_reduced"] += 1

            _log.info(
                "position_size_reduced",
                extra={
                    "symbol": symbol,
                    "regime": regime.value,
                    "original_amount": str(original_amount),
                    "reduced_amount": str(amount),
                    "factor": self._policy.risk_small_size_factor,
                    "trace_id": trace_id,
                },
            )

            # Emit event if configured (use existing topic)
            if self._event_bus and self._policy.emit_blocked_events:
                await self._event_bus.publish(
                    EventTopics.TRADE_PARTIAL_FOLLOWUP,
                    {
                        "symbol": symbol,
                        "regime": regime.value,
                        "original_amount": float(original_amount),
                        "reduced_amount": float(amount),
                        "factor": self._policy.risk_small_size_factor,
                        "trace_id": trace_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "reason": "risk_small size reduction",
                    },
                )

        return amount

    async def _check_regime_for_sells(self, symbol: str, trace_id: str) -> None:
        """
        Check if sells should be restricted (rare case).

        Most policies allow sells even in risk_off for exits.
        """
        if self._policy.allow_exits_when_restricted:
            return  # Sells allowed

        regime = await self._get_current_regime()

        if regime in (RegimeState.RISK_OFF, RegimeState.NEUTRAL):
            self._handle_blocked_operation(
                regime=regime,
                operation="sell",
                symbol=symbol,
                reason=f"Sells restricted in {regime.value} regime",
                trace_id=trace_id,
            )

            raise RegimeBlockedException(
                regime=regime,
                operation="sell",
                symbol=symbol,
                reason=f"{regime.value} regime blocks sells",
                trace_id=trace_id,
            )

    def _handle_blocked_operation(
        self,
        regime: RegimeState,
        operation: str,
        symbol: str,
        reason: str,
        trace_id: str,
    ) -> None:
        """Handle blocked operation - logging and events."""
        self._stats["operations_blocked"] += 1

        # Log if configured
        if self._policy.log_blocked_operations:
            _log.warning(
                "operation_blocked_by_regime",
                extra={
                    "regime": regime.value,
                    "operation": operation,
                    "symbol": symbol,
                    "reason": reason,
                    "trace_id": trace_id,
                },
            )

        # Emit event if configured (use existing TRADE_BLOCKED topic)
        if self._event_bus and self._policy.emit_blocked_events:
            asyncio.create_task(
                self._event_bus.publish(
                    EventTopics.TRADE_BLOCKED,
                    {
                        "regime": regime.value,
                        "operation": operation,
                        "symbol": symbol,
                        "reason": reason,
                        "trace_id": trace_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            )

    # ============== Statistics ==============

    def get_statistics(self) -> dict[str, int]:
        """Get gated broker statistics."""
        return self._stats.copy()

    def reset_statistics(self) -> None:
        """Reset statistics counters."""
        self._stats = {
            "operations_allowed": 0,
            "operations_blocked": 0,
            "operations_reduced": 0,
        }


# ============== Factory Function ==============

def create_gated_broker(
    inner_broker: BrokerPort,
    regime_detector: Optional[RegimeDetector] = None,
    settings: Optional[Any] = None,
    event_bus: Optional[Any] = None,
) -> GatedBroker:
    """
    Factory function to create configured GatedBroker.

    Args:
        inner_broker: Underlying broker
        regime_detector: Optional regime detector
        settings: Optional settings for policy
        event_bus: Optional event bus

    Returns:
        Configured GatedBroker instance
    """
    # Create policy from settings if provided
    policy = RegimePolicy()

    if settings:
        factor = float(getattr(settings, "REGIME_RISK_SMALL_SIZE_FACTOR", 0.5))
        # clamp factor to [0.0, 1.0]
        clamped_factor = max(0.0, min(1.0, factor))

        if factor != clamped_factor:
            _log.warning(
                "risk_small_size_factor_clamped",
                extra={"given": factor, "used": clamped_factor},
            )

        policy = RegimePolicy(
            block_longs_on_risk_off=getattr(
                settings, "REGIME_BLOCK_LONGS_ON_RISK_OFF", True
            ),
            block_longs_on_neutral=getattr(
                settings, "REGIME_BLOCK_LONGS_ON_NEUTRAL", True
            ),
            allow_exits_when_restricted=getattr(
                settings, "REGIME_ALLOW_EXITS_WHEN_RESTRICTED", True
            ),
            reduce_size_on_risk_small=getattr(
                settings, "REGIME_REDUCE_SIZE_ON_RISK_SMALL", True
            ),
            risk_small_size_factor=clamped_factor,
            log_blocked_operations=getattr(
                settings, "REGIME_LOG_BLOCKED_OPERATIONS", True
            ),
            emit_blocked_events=getattr(
                settings, "REGIME_EMIT_BLOCKED_EVENTS", True
            ),
        )

    return GatedBroker(
        inner=inner_broker,
        regime_detector=regime_detector,
        policy=policy,
        event_bus=event_bus,
    )
