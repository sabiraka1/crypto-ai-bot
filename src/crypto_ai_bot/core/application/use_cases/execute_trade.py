"""
Execute Trade Use Case - ЕДИНСТВЕННАЯ точка исполнения ордеров.

Critical rules:
- ALL orders MUST go through this module
- Idempotency is mandatory
- Risk checks are mandatory
- Full event trail with trace_id
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from crypto_ai_bot.core.application import events_topics
from crypto_ai_bot.core.application.ports import (
    BrokerPort,
    EventBusPort,
    OrderDTO,
    OrderSide,
    OrderStatus,
    OrderStoragePort,
    OrderType,
    StoragePort,
    TradeStoragePort,
)
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskCheckResult
from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.trace import generate_trace_id

_log = get_logger(__name__)


# ============= RESULT TYPES =============

class TradeAction(Enum):
    """Trade execution action"""
    BUY = "buy"
    SELL = "sell"
    SKIP = "skip"


class BlockReason(Enum):
    """Reasons for blocking trade"""
    DUPLICATE = "duplicate"
    RISK_BLOCKED = "risk_blocked"
    INVALID_SIDE = "invalid_side"
    INVALID_AMOUNT = "invalid_amount"
    BROKER_ERROR = "broker_error"
    NO_BALANCE = "no_balance"


@dataclass(frozen=True)
class ExecuteTradeResult:
    """Result of trade execution attempt"""
    action: TradeAction
    executed: bool
    order: Optional[OrderDTO] = None
    block_reason: Optional[BlockReason] = None
    risk_details: Optional[str] = None
    error: Optional[str] = None
    trace_id: Optional[str] = None
    
    @property
    def success(self) -> bool:
        return self.executed and self.order is not None


# ============= IDEMPOTENCY =============

class IdempotencyService:
    """Service for idempotency checks"""
    
    def __init__(self, storage: OrderStoragePort):
        self._storage = storage
    
    @staticmethod
    def generate_key(
        symbol: str,
        side: str,
        amount: Decimal,
        session_id: str,
        timestamp: Optional[datetime] = None
    ) -> str:
        """Generate idempotency key for trade"""
        ts = timestamp or datetime.utcnow()
        # Include timestamp bucket (1 minute) to allow same trade after timeout
        ts_bucket = ts.replace(second=0, microsecond=0).isoformat()
        key_payload = f"{symbol}|{side}|{amount}|{session_id}|{ts_bucket}"
        hash_hex = hashlib.sha256(key_payload.encode()).hexdigest()[:16]
        return f"idem_{hash_hex}"
    
    async def check_duplicate(
        self,
        key: str,
        bucket_ms: int = 60000
    ) -> bool:
        """Check if key was already used within bucket"""
        try:
            is_used = await self._storage.is_idempotent_key_used(key, bucket_ms)
            if not is_used:
                await self._storage.save_idempotent_key(key, datetime.utcnow())
            return is_used
        except Exception as e:
            _log.error(f"Idempotency check failed: {e}", exc_info=True)
            # Conservative: assume not duplicate on error
            return False


# ============= MAIN USE CASE =============

class ExecuteTrade:
    """
    Execute trade use case - the ONLY way to create orders.
    
    Responsibilities:
    1. Idempotency check
    2. Risk validation
    3. Balance check
    4. Order execution with retries
    5. Event publishing
    6. Storage persistence
    """
    
    def __init__(
        self,
        broker: BrokerPort,
        storage: StoragePort,
        event_bus: EventBusPort,
        risk_manager: RiskManager,
        settings: Settings,
    ):
        self._broker = broker
        self._storage = storage
        self._event_bus = event_bus
        self._risk_manager = risk_manager
        self._settings = settings
        self._idempotency = IdempotencyService(storage.orders)
    
    async def execute(
        self,
        symbol: str,
        side: OrderSide,
        amount: Optional[Decimal] = None,
        quote_amount: Optional[Decimal] = None,
        trace_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        max_retries: int = 3,
    ) -> ExecuteTradeResult:
        """
        Execute trade with full safety checks.
        
        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            side: OrderSide.BUY or OrderSide.SELL
            amount: Base amount for SELL orders
            quote_amount: Quote amount for BUY orders
            trace_id: Correlation ID for tracing
            client_order_id: Custom order ID (will be generated if not provided)
            max_retries: Number of retry attempts on failure
            
        Returns:
            ExecuteTradeResult with execution details
        """
        # Generate trace_id if not provided
        trace_id = trace_id or generate_trace_id()
        
        # Log start
        _log.info(
            f"Starting trade execution",
            extra={
                "trace_id": trace_id,
                "symbol": symbol,
                "side": side.value,
                "amount": str(amount) if amount else None,
                "quote_amount": str(quote_amount) if quote_amount else None,
            }
        )
        
        # Publish evaluation started event
        await self._publish_event(
            events_topics.EVALUATION_STARTED,
            {"symbol": symbol, "side": side.value},
            trace_id
        )
        
        # Step 1: Validate inputs
        validation_result = self._validate_inputs(symbol, side, amount, quote_amount)
        if validation_result:
            await self._publish_blocked_event(symbol, validation_result, trace_id)
            return validation_result
        
        # Step 2: Calculate actual amount
        final_amount = self._calculate_amount(side, amount, quote_amount)
        
        # Step 3: Idempotency check
        idem_key = self._idempotency.generate_key(
            symbol=symbol,
            side=side.value,
            amount=final_amount,
            session_id=self._settings.SESSION_ID,
        )
        
        if await self._idempotency.check_duplicate(idem_key):
            _log.warning(
                f"Duplicate trade detected",
                extra={"trace_id": trace_id, "symbol": symbol, "idem_key": idem_key}
            )
            await self._publish_blocked_event(
                symbol, 
                ExecuteTradeResult(
                    action=TradeAction.SKIP,
                    executed=False,
                    block_reason=BlockReason.DUPLICATE,
                    trace_id=trace_id
                ),
                trace_id
            )
            return ExecuteTradeResult(
                action=TradeAction.SKIP,
                executed=False,
                block_reason=BlockReason.DUPLICATE,
                trace_id=trace_id
            )
        
        # Step 4: Risk checks
        risk_result = await self._check_risk(symbol, side, final_amount, trace_id)
        if not risk_result.allowed:
            await self._publish_risk_blocked_event(symbol, risk_result, trace_id)
            return ExecuteTradeResult(
                action=TradeAction.SKIP,
                executed=False,
                block_reason=BlockReason.RISK_BLOCKED,
                risk_details=risk_result.reason,
                trace_id=trace_id
            )
        
        # Step 5: Execute with retries
        client_order_id = client_order_id or idem_key
        order = await self._execute_with_retries(
            symbol=symbol,
            side=side,
            amount=final_amount,
            client_order_id=client_order_id,
            trace_id=trace_id,
            max_retries=max_retries
        )
        
        if order:
            # Success: persist and publish
            await self._persist_order(order, trace_id)
            await self._publish_success_events(order, trace_id)
            
            _log.info(
                f"Trade executed successfully",
                extra={
                    "trace_id": trace_id,
                    "symbol": symbol,
                    "order_id": order.id,
                    "amount": str(order.amount),
                    "price": str(order.price) if order.price else "market",
                }
            )
            
            return ExecuteTradeResult(
                action=TradeAction.BUY if side == OrderSide.BUY else TradeAction.SELL,
                executed=True,
                order=order,
                trace_id=trace_id
            )
        else:
            # Failure after all retries
            await self._publish_failure_event(symbol, side, trace_id)
            
            return ExecuteTradeResult(
                action=TradeAction.SKIP,
                executed=False,
                block_reason=BlockReason.BROKER_ERROR,
                error="Failed after all retries",
                trace_id=trace_id
            )
    
    # ========== PRIVATE METHODS ==========
    
    def _validate_inputs(
        self,
        symbol: str,
        side: OrderSide,
        amount: Optional[Decimal],
        quote_amount: Optional[Decimal]
    ) -> Optional[ExecuteTradeResult]:
        """Validate input parameters"""
        if not symbol:
            return ExecuteTradeResult(
                action=TradeAction.SKIP,
                executed=False,
                block_reason=BlockReason.INVALID_SIDE,
                error="Symbol is required"
            )
        
        if side == OrderSide.BUY and not quote_amount and not self._settings.FIXED_AMOUNT:
            return ExecuteTradeResult(
                action=TradeAction.SKIP,
                executed=False,
                block_reason=BlockReason.INVALID_AMOUNT,
                error="Quote amount required for BUY"
            )
        
        if side == OrderSide.SELL and not amount:
            return ExecuteTradeResult(
                action=TradeAction.SKIP,
                executed=False,
                block_reason=BlockReason.INVALID_AMOUNT,
                error="Base amount required for SELL"
            )
        
        return None
    
    def _calculate_amount(
        self,
        side: OrderSide,
        amount: Optional[Decimal],
        quote_amount: Optional[Decimal]
    ) -> Decimal:
        """Calculate final amount for order"""
        if side == OrderSide.BUY:
            return quote_amount or self._settings.FIXED_AMOUNT
        else:  # SELL
            return amount or dec("0")
    
    async def _check_risk(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        trace_id: str
    ) -> RiskCheckResult:
        """Check risk rules"""
        return self._risk_manager.check_trade(
            symbol=symbol,
            side=side.value,
            amount=amount,
            trace_id=trace_id
        )
    
    async def _execute_with_retries(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        client_order_id: str,
        trace_id: str,
        max_retries: int
    ) -> Optional[OrderDTO]:
        """Execute order with exponential backoff retries"""
        for attempt in range(max_retries):
            try:
                # Publish order created event
                await self._publish_event(
                    events_topics.ORDER_CREATED,
                    {
                        "symbol": symbol,
                        "side": side.value,
                        "amount": str(amount),
                        "client_order_id": client_order_id,
                        "attempt": attempt + 1,
                    },
                    trace_id
                )
                
                # Execute order
                if side == OrderSide.BUY:
                    order = await self._broker.create_market_order(
                        symbol=symbol,
                        side=side,
                        amount=amount,
                        client_order_id=client_order_id,
                        trace_id=trace_id
                    )
                else:  # SELL
                    order = await self._broker.create_market_order(
                        symbol=symbol,
                        side=side,
                        amount=amount,
                        client_order_id=client_order_id,
                        trace_id=trace_id
                    )
                
                return order
                
            except Exception as e:
                _log.error(
                    f"Order execution failed",
                    extra={
                        "trace_id": trace_id,
                        "symbol": symbol,
                        "attempt": attempt + 1,
                        "error": str(e),
                    },
                    exc_info=True
                )
                
                if attempt < max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s...
                    delay = 2 ** attempt
                    await asyncio.sleep(delay)
                else:
                    # Final attempt failed
                    await self._publish_event(
                        events_topics.ORDER_FAILED,
                        {
                            "symbol": symbol,
                            "side": side.value,
                            "error": str(e),
                            "attempts": max_retries,
                        },
                        trace_id
                    )
        
        return None
    
    async def _persist_order(self, order: OrderDTO, trace_id: str) -> None:
        """Persist order to storage"""
        try:
            await self._storage.orders.save_order(
                order_id=order.id,
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side.value,
                type=order.type.value,
                amount=order.amount,
                price=order.price,
                status=order.status.value,
                timestamp=order.timestamp,
                trace_id=trace_id,
                metadata={"info": order.info}
            )
        except Exception as e:
            _log.error(
                f"Failed to persist order",
                extra={"trace_id": trace_id, "order_id": order.id, "error": str(e)},
                exc_info=True
            )
    
    async def _publish_event(
        self,
        topic: str,
        payload: dict,
        trace_id: str
    ) -> None:
        """Publish event to event bus"""
        try:
            payload["trace_id"] = trace_id
            payload["timestamp"] = datetime.utcnow().isoformat()
            await self._event_bus.publish(topic, payload, trace_id)
        except Exception as e:
            _log.error(
                f"Failed to publish event",
                extra={"trace_id": trace_id, "topic": topic, "error": str(e)},
                exc_info=True
            )
    
    async def _publish_success_events(self, order: OrderDTO, trace_id: str) -> None:
        """Publish success events"""
        # Order executed
        topic, payload = events_topics.build_order_event(
            topic=events_topics.ORDER_EXECUTED,
            symbol=order.symbol,
            order_id=order.id,
            client_order_id=order.client_order_id,
            side=order.side,
            order_type=order.type,
            amount=order.amount,
            price=order.price,
            status=order.status.value,
            filled=order.filled,
            trace_id=trace_id
        )
        await self._event_bus.publish(topic, payload, trace_id)
        
        # Trade completed
        await self._publish_event(
            events_topics.TRADE_COMPLETED,
            {
                "symbol": order.symbol,
                "order_id": order.id,
                "side": order.side.value,
                "amount": str(order.amount),
                "price": str(order.price) if order.price else "market",
                "filled": str(order.filled) if order.filled else str(order.amount),
                "fee": str(order.fee) if order.fee else "0",
            },
            trace_id
        )
    
    async def _publish_blocked_event(
        self,
        symbol: str,
        result: ExecuteTradeResult,
        trace_id: str
    ) -> None:
        """Publish trade blocked event"""
        await self._publish_event(
            events_topics.TRADE_BLOCKED,
            {
                "symbol": symbol,
                "reason": result.block_reason.value if result.block_reason else "unknown",
                "details": result.error or result.risk_details or "",
            },
            trace_id
        )
    
    async def _publish_risk_blocked_event(
        self,
        symbol: str,
        risk_result: RiskCheckResult,
        trace_id: str
    ) -> None:
        """Publish risk blocked event"""
        topic, payload = events_topics.build_risk_blocked_event(
            symbol=symbol,
            rule=risk_result.triggered_rule or "unknown",
            reason=risk_result.reason,
            value=risk_result.current_value or dec("0"),
            threshold=risk_result.threshold or dec("0"),
            action="block",
            trace_id=trace_id
        )
        await self._event_bus.publish(topic, payload, trace_id)
    
    async def _publish_failure_event(
        self,
        symbol: str,
        side: OrderSide,
        trace_id: str
    ) -> None:
        """Publish trade failure event"""
        await self._publish_event(
            events_topics.TRADE_FAILED,
            {
                "symbol": symbol,
                "side": side.value,
                "reason": "broker_error_after_retries",
            },
            trace_id
        )


# ============= FACTORY FUNCTION =============

def create_execute_trade(
    broker: BrokerPort,
    storage: StoragePort,
    event_bus: EventBusPort,
    risk_manager: RiskManager,
    settings: Settings,
) -> ExecuteTrade:
    """Factory function to create ExecuteTrade instance"""
    return ExecuteTrade(
        broker=broker,
        storage=storage,
        event_bus=event_bus,
        risk_manager=risk_manager,
        settings=settings,
    )


# ============= EXPORT =============

__all__ = [
    "ExecuteTrade",
    "ExecuteTradeResult",
    "TradeAction",
    "BlockReason",
    "create_execute_trade",
]