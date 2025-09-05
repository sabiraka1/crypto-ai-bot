"""
Event topics registry for the crypto trading system.

This module defines all event topics used across the application.
It serves as the single source of truth for event names and payload schemas.
No magic strings allowed!
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final, TypedDict, Optional, Literal

from crypto_ai_bot.utils.decimal import dec


# ============================================================================
# BROKER & ORDERS
# ============================================================================

ORDER_CREATED: Final[str] = "order.created"
ORDER_EXECUTED: Final[str] = "order.executed"
ORDER_PARTIALLY_FILLED: Final[str] = "order.partially.filled"
ORDER_FAILED: Final[str] = "order.failed"
ORDER_CANCELLED: Final[str] = "order.cancelled"

# ============================================================================
# TRADE LIFECYCLE
# ============================================================================

TRADE_SIGNAL: Final[str] = "trade.signal"
TRADE_INITIATED: Final[str] = "trade.initiated"
TRADE_COMPLETED: Final[str] = "trade.completed"
TRADE_FAILED: Final[str] = "trade.failed"
TRADE_SETTLED: Final[str] = "trade.settled"
TRADE_SETTLEMENT_TIMEOUT: Final[str] = "trade.settlement.timeout"
TRADE_BLOCKED: Final[str] = "trade.blocked"
TRADE_PARTIAL_FOLLOWUP: Final[str] = "trade.partial.followup"

# ============================================================================
# SIGNALS & STRATEGIES
# ============================================================================

SIGNAL_GENERATED: Final[str] = "signal.generated"
SIGNAL_FILTERED: Final[str] = "signal.filtered"
SIGNAL_REJECTED: Final[str] = "signal.rejected"
STRATEGY_ACTIVATED: Final[str] = "strategy.activated"
STRATEGY_DEACTIVATED: Final[str] = "strategy.deactivated"

# ============================================================================
# MARKET REGIME
# ============================================================================

REGIME_CHANGED: Final[str] = "regime.changed"
REGIME_RISK_OFF: Final[str] = "regime.risk_off"
REGIME_RISK_SMALL: Final[str] = "regime.risk_small"
REGIME_NEUTRAL: Final[str] = "regime.neutral"
REGIME_RISK_ON: Final[str] = "regime.risk_on"

# ============================================================================
# PROTECTIVE EXITS
# ============================================================================

EXIT_STOP_TRIGGERED: Final[str] = "exit.stop.triggered"
EXIT_TRAILING_UPDATED: Final[str] = "exit.trailing.updated"
EXIT_TP1_REACHED: Final[str] = "exit.tp1.reached"
EXIT_TP2_REACHED: Final[str] = "exit.tp2.reached"
EXIT_BREAKEVEN_SET: Final[str] = "exit.breakeven.set"

# ============================================================================
# POSITION MANAGEMENT
# ============================================================================

POSITION_OPENED: Final[str] = "position.opened"
POSITION_UPDATED: Final[str] = "position.updated"
POSITION_CLOSED: Final[str] = "position.closed"

# ============================================================================
# HEALTH & MONITORING
# ============================================================================

WATCHDOG_HEARTBEAT: Final[str] = "watchdog.heartbeat"
HEALTH_REPORT: Final[str] = "health.report"
HEALTH_CHECK_FAILED: Final[str] = "health.check.failed"
METRICS_UPDATED: Final[str] = "metrics.updated"

# ============================================================================
# RISK & BUDGETS
# ============================================================================

RISK_BLOCKED: Final[str] = "risk.blocked"
RISK_RULE_TRIGGERED: Final[str] = "risk.rule.triggered"
BUDGET_EXCEEDED: Final[str] = "budget.exceeded"
DRAWDOWN_WARNING: Final[str] = "drawdown.warning"
LOSS_STREAK_WARNING: Final[str] = "loss.streak.warning"
COOLDOWN_ACTIVATED: Final[str] = "cooldown.activated"

# ============================================================================
# PNL & REPORTING
# ============================================================================

PNL_UPDATED: Final[str] = "pnl.updated"
PNL_DAILY_REPORT: Final[str] = "pnl.daily.report"
PNL_WEEKLY_REPORT: Final[str] = "pnl.weekly.report"

# ============================================================================
# EVALUATION & DECISION
# ============================================================================

EVALUATION_STARTED: Final[str] = "evaluation.started"
EVALUATION_COMPLETED: Final[str] = "evaluation.completed"
DECISION_EVALUATED: Final[str] = "decision.evaluated"

# ============================================================================
# RECONCILIATION
# ============================================================================

RECONCILIATION_STARTED: Final[str] = "reconciliation.started"
RECONCILIATION_COMPLETED: Final[str] = "reconciliation.completed"
RECONCILE_POSITION_MISMATCH: Final[str] = "reconcile.position.mismatch"
RECONCILE_BALANCE_MISMATCH: Final[str] = "reconcile.balance.mismatch"
RECONCILE_ORDER_PHANTOM: Final[str] = "reconcile.order.phantom"

# ============================================================================
# ORCHESTRATOR
# ============================================================================

ORCH_STARTED: Final[str] = "orch.started"
ORCH_STOPPED: Final[str] = "orch.stopped"
ORCH_PAUSED: Final[str] = "orch.paused"
ORCH_RESUMED: Final[str] = "orch.resumed"
ORCH_AUTO_PAUSED: Final[str] = "orch.auto.paused"
ORCH_AUTO_RESUMED: Final[str] = "orch.auto.resumed"
ORCH_CYCLE_STARTED: Final[str] = "orch.cycle.started"
ORCH_CYCLE_COMPLETED: Final[str] = "orch.cycle.completed"

# ============================================================================
# SAFETY & EMERGENCY
# ============================================================================

DMS_ACTIVATED: Final[str] = "dms.activated"
DMS_TRIGGERED: Final[str] = "dms.triggered"
DMS_SKIPPED: Final[str] = "dms.skipped"
DMS_PING: Final[str] = "dms.ping"
EMERGENCY_STOP: Final[str] = "emergency.stop"
INSTANCE_LOCK_ACQUIRED: Final[str] = "instance.lock.acquired"
INSTANCE_LOCK_FAILED: Final[str] = "instance.lock.failed"

# ============================================================================
# ALERTING & NOTIFICATIONS
# ============================================================================

ALERT_SENT: Final[str] = "alert.sent"
ALERT_CRITICAL: Final[str] = "alert.critical"
ALERT_WARNING: Final[str] = "alert.warning"
ALERT_INFO: Final[str] = "alert.info"
TELEGRAM_MESSAGE_SENT: Final[str] = "telegram.message.sent"

# ============================================================================
# SYSTEM ERRORS
# ============================================================================

BROKER_ERROR: Final[str] = "broker.error"
STORAGE_ERROR: Final[str] = "storage.error"
API_ERROR: Final[str] = "api.error"
NETWORK_ERROR: Final[str] = "network.error"


# ============================================================================
# PAYLOAD SCHEMAS (TypedDict for type safety)
# ============================================================================

class BaseEventPayload(TypedDict):
    """Base payload with common fields"""
    trace_id: str
    timestamp: str  # ISO format
    symbol: str


class OrderPayload(BaseEventPayload):
    """Order event payload"""
    order_id: str
    client_order_id: str
    side: Literal["buy", "sell"]
    type: Literal["market", "limit", "stop"]
    amount: str  # Decimal as string
    price: Optional[str]  # Decimal as string
    status: str
    filled: Optional[str]  # Decimal as string


class TradePayload(BaseEventPayload):
    """Trade event payload"""
    trade_id: str
    order_id: str
    side: Literal["buy", "sell"]
    amount: str  # Decimal as string
    price: str  # Decimal as string
    fee: str  # Decimal as string
    fee_currency: str


class SignalPayload(BaseEventPayload):
    """Signal event payload"""
    signal_id: str
    strategy: str
    direction: Literal["long", "short", "neutral"]
    strength: float  # 0.0 to 1.0
    timeframe: str
    confidence: float  # 0.0 to 1.0


class RegimePayload(TypedDict):
    """Regime change event payload"""
    trace_id: str
    timestamp: str
    old_state: Literal["risk_on", "risk_small", "neutral", "risk_off"]
    new_state: Literal["risk_on", "risk_small", "neutral", "risk_off"]
    score: float
    dxy_change: Optional[float]
    btc_dom_change: Optional[float]
    fomc_active: bool


class RiskBlockedPayload(BaseEventPayload):
    """Risk blocked event payload"""
    rule: str
    reason: str
    value: str  # Current value that triggered
    threshold: str  # Threshold that was exceeded
    action: Literal["block", "reduce", "warn"]


class PnLPayload(BaseEventPayload):
    """PnL event payload"""
    realized_pnl: str  # Decimal as string
    unrealized_pnl: str  # Decimal as string
    total_pnl: str  # Decimal as string
    trade_count: int
    win_rate: float
    period: Literal["daily", "weekly", "monthly", "all_time"]


class PositionPayload(BaseEventPayload):
    """Position event payload"""
    position_id: str
    side: Literal["long"]  # SPOT only
    amount: str  # Decimal as string
    entry_price: str  # Decimal as string
    current_price: Optional[str]  # Decimal as string
    unrealized_pnl: Optional[str]  # Decimal as string
    stop_loss: Optional[str]  # Decimal as string
    take_profit: Optional[str]  # Decimal as string


class HealthPayload(TypedDict):
    """Health check event payload"""
    trace_id: str
    timestamp: str
    status: Literal["healthy", "degraded", "unhealthy"]
    components: dict[str, bool]  # {"db": True, "broker": True, ...}
    latency_ms: Optional[float]
    error: Optional[str]


class AlertPayload(TypedDict):
    """Alert event payload"""
    trace_id: str
    timestamp: str
    severity: Literal["info", "warning", "error", "critical"]
    title: str
    message: str
    metadata: Optional[dict[str, any]]


# ============================================================================
# EVENT BUILDERS (Type-safe event construction)
# ============================================================================

def build_order_event(
    topic: str,
    symbol: str,
    order_id: str,
    client_order_id: str,
    side: Literal["buy", "sell"],
    order_type: Literal["market", "limit", "stop"],
    amount: Decimal,
    price: Optional[Decimal],
    status: str,
    filled: Optional[Decimal],
    trace_id: str
) -> tuple[str, OrderPayload]:
    """Build order event with proper typing"""
    return topic, OrderPayload(
        trace_id=trace_id,
        timestamp=datetime.utcnow().isoformat(),
        symbol=symbol,
        order_id=order_id,
        client_order_id=client_order_id,
        side=side,
        type=order_type,
        amount=str(amount),
        price=str(price) if price else None,
        status=status,
        filled=str(filled) if filled else None
    )


def build_trade_event(
    topic: str,
    symbol: str,
    trade_id: str,
    order_id: str,
    side: Literal["buy", "sell"],
    amount: Decimal,
    price: Decimal,
    fee: Decimal,
    fee_currency: str,
    trace_id: str
) -> tuple[str, TradePayload]:
    """Build trade event with proper typing"""
    return topic, TradePayload(
        trace_id=trace_id,
        timestamp=datetime.utcnow().isoformat(),
        symbol=symbol,
        trade_id=trade_id,
        order_id=order_id,
        side=side,
        amount=str(amount),
        price=str(price),
        fee=str(fee),
        fee_currency=fee_currency
    )


def build_risk_blocked_event(
    symbol: str,
    rule: str,
    reason: str,
    value: Decimal,
    threshold: Decimal,
    action: Literal["block", "reduce", "warn"],
    trace_id: str
) -> tuple[str, RiskBlockedPayload]:
    """Build risk blocked event with proper typing"""
    return RISK_BLOCKED, RiskBlockedPayload(
        trace_id=trace_id,
        timestamp=datetime.utcnow().isoformat(),
        symbol=symbol,
        rule=rule,
        reason=reason,
        value=str(value),
        threshold=str(threshold),
        action=action
    )


def build_pnl_event(
    topic: str,
    symbol: str,
    realized_pnl: Decimal,
    unrealized_pnl: Decimal,
    trade_count: int,
    win_rate: float,
    period: Literal["daily", "weekly", "monthly", "all_time"],
    trace_id: str
) -> tuple[str, PnLPayload]:
    """Build PnL event with proper typing"""
    total_pnl = realized_pnl + unrealized_pnl
    return topic, PnLPayload(
        trace_id=trace_id,
        timestamp=datetime.utcnow().isoformat(),
        symbol=symbol,
        realized_pnl=str(realized_pnl),
        unrealized_pnl=str(unrealized_pnl),
        total_pnl=str(total_pnl),
        trade_count=trade_count,
        win_rate=win_rate,
        period=period
    )


def build_regime_event(
    old_state: str,
    new_state: str,
    score: float,
    dxy_change: Optional[float],
    btc_dom_change: Optional[float],
    fomc_active: bool,
    trace_id: str
) -> tuple[str, RegimePayload]:
    """Build regime change event with proper typing"""
    return REGIME_CHANGED, RegimePayload(
        trace_id=trace_id,
        timestamp=datetime.utcnow().isoformat(),
        old_state=old_state,
        new_state=new_state,
        score=score,
        dxy_change=dxy_change,
        btc_dom_change=btc_dom_change,
        fomc_active=fomc_active
    )


# ============================================================================
# TOPIC GROUPS (for easier management)
# ============================================================================

class TopicGroups:
    """Grouped event topics for easier access and subscription"""

    ORDERS = [
        ORDER_CREATED,
        ORDER_EXECUTED,
        ORDER_PARTIALLY_FILLED,
        ORDER_FAILED,
        ORDER_CANCELLED,
    ]

    TRADES = [
        TRADE_SIGNAL,
        TRADE_INITIATED,
        TRADE_COMPLETED,
        TRADE_FAILED,
        TRADE_SETTLED,
        TRADE_SETTLEMENT_TIMEOUT,
        TRADE_BLOCKED,
        TRADE_PARTIAL_FOLLOWUP,
    ]

    SIGNALS = [
        SIGNAL_GENERATED,
        SIGNAL_FILTERED,
        SIGNAL_REJECTED,
        STRATEGY_ACTIVATED,
        STRATEGY_DEACTIVATED,
    ]

    REGIME = [
        REGIME_CHANGED,
        REGIME_RISK_OFF,
        REGIME_RISK_SMALL,
        REGIME_NEUTRAL,
        REGIME_RISK_ON,
    ]

    EXITS = [
        EXIT_STOP_TRIGGERED,
        EXIT_TRAILING_UPDATED,
        EXIT_TP1_REACHED,
        EXIT_TP2_REACHED,
        EXIT_BREAKEVEN_SET,
    ]

    POSITIONS = [
        POSITION_OPENED,
        POSITION_UPDATED,
        POSITION_CLOSED,
    ]

    HEALTH = [
        WATCHDOG_HEARTBEAT,
        HEALTH_REPORT,
        HEALTH_CHECK_FAILED,
        METRICS_UPDATED,
    ]

    RISK = [
        RISK_BLOCKED,
        RISK_RULE_TRIGGERED,
        BUDGET_EXCEEDED,
        DRAWDOWN_WARNING,
        LOSS_STREAK_WARNING,
        COOLDOWN_ACTIVATED,
    ]

    PNL = [
        PNL_UPDATED,
        PNL_DAILY_REPORT,
        PNL_WEEKLY_REPORT,
    ]

    EVALUATION = [
        EVALUATION_STARTED,
        EVALUATION_COMPLETED,
        DECISION_EVALUATED,
    ]

    RECONCILIATION = [
        RECONCILIATION_STARTED,
        RECONCILIATION_COMPLETED,
        RECONCILE_POSITION_MISMATCH,
        RECONCILE_BALANCE_MISMATCH,
        RECONCILE_ORDER_PHANTOM,
    ]

    ORCHESTRATOR = [
        ORCH_STARTED,
        ORCH_STOPPED,
        ORCH_PAUSED,
        ORCH_RESUMED,
        ORCH_AUTO_PAUSED,
        ORCH_AUTO_RESUMED,
        ORCH_CYCLE_STARTED,
        ORCH_CYCLE_COMPLETED,
    ]

    SAFETY = [
        DMS_ACTIVATED,
        DMS_TRIGGERED,
        DMS_SKIPPED,
        DMS_PING,
        EMERGENCY_STOP,
        INSTANCE_LOCK_ACQUIRED,
        INSTANCE_LOCK_FAILED,
    ]

    ALERTS = [
        ALERT_SENT,
        ALERT_CRITICAL,
        ALERT_WARNING,
        ALERT_INFO,
        TELEGRAM_MESSAGE_SENT,
    ]

    ERRORS = [
        BROKER_ERROR,
        STORAGE_ERROR,
        API_ERROR,
        NETWORK_ERROR,
    ]

    # Critical events that always need attention
    CRITICAL = [
        ORDER_FAILED,
        TRADE_FAILED,
        RISK_BLOCKED,
        DMS_TRIGGERED,
        EMERGENCY_STOP,
        ALERT_CRITICAL,
        BROKER_ERROR,
        STORAGE_ERROR,
    ]

    # Events for Telegram notifications
    TELEGRAM_NOTIFY = [
        TRADE_COMPLETED,
        TRADE_FAILED,
        RISK_BLOCKED,
        PNL_DAILY_REPORT,
        REGIME_CHANGED,
        DMS_TRIGGERED,
        ALERT_CRITICAL,
        ALERT_WARNING,
    ]

    @classmethod
    def all_topics(cls) -> list[str]:
        """Get all defined topics"""
        topics = set()
        for attr_name in dir(cls):
            if not attr_name.startswith("_") and attr_name.isupper():
                attr = getattr(cls, attr_name)
                if isinstance(attr, list):
                    topics.update(attr)
        return sorted(list(topics))

    @classmethod
    def get_group(cls, group_name: str) -> list[str]:
        """Get topics for a specific group"""
        return getattr(cls, group_name.upper(), [])


def is_valid_topic(topic: str) -> bool:
    """Check if a topic is valid"""
    return topic in TopicGroups.all_topics()


def requires_notification(topic: str) -> bool:
    """Check if topic requires Telegram notification"""
    return topic in TopicGroups.TELEGRAM_NOTIFY


def is_critical(topic: str) -> bool:
    """Check if topic is critical"""
    return topic in TopicGroups.CRITICAL


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    # Main topics - Orders
    "ORDER_CREATED",
    "ORDER_EXECUTED",
    "ORDER_PARTIALLY_FILLED",
    "ORDER_FAILED",
    "ORDER_CANCELLED",
    
    # Trades
    "TRADE_SIGNAL",
    "TRADE_INITIATED",
    "TRADE_COMPLETED",
    "TRADE_FAILED",
    "TRADE_SETTLED",
    "TRADE_SETTLEMENT_TIMEOUT",
    "TRADE_BLOCKED",
    "TRADE_PARTIAL_FOLLOWUP",
    
    # Signals & Strategies
    "SIGNAL_GENERATED",
    "SIGNAL_FILTERED",
    "SIGNAL_REJECTED",
    "STRATEGY_ACTIVATED",
    "STRATEGY_DEACTIVATED",
    
    # Regime
    "REGIME_CHANGED",
    "REGIME_RISK_OFF",
    "REGIME_RISK_SMALL",
    "REGIME_NEUTRAL",
    "REGIME_RISK_ON",
    
    # Protective Exits
    "EXIT_STOP_TRIGGERED",
    "EXIT_TRAILING_UPDATED",
    "EXIT_TP1_REACHED",
    "EXIT_TP2_REACHED",
    "EXIT_BREAKEVEN_SET",
    
    # Positions
    "POSITION_OPENED",
    "POSITION_UPDATED",
    "POSITION_CLOSED",
    
    # Health
    "WATCHDOG_HEARTBEAT",
    "HEALTH_REPORT",
    "HEALTH_CHECK_FAILED",
    "METRICS_UPDATED",
    
    # Risk
    "RISK_BLOCKED",
    "RISK_RULE_TRIGGERED",
    "BUDGET_EXCEEDED",
    "DRAWDOWN_WARNING",
    "LOSS_STREAK_WARNING",
    "COOLDOWN_ACTIVATED",
    
    # PnL
    "PNL_UPDATED",
    "PNL_DAILY_REPORT",
    "PNL_WEEKLY_REPORT",
    
    # Evaluation
    "EVALUATION_STARTED",
    "EVALUATION_COMPLETED",
    "DECISION_EVALUATED",
    
    # Reconciliation
    "RECONCILIATION_STARTED",
    "RECONCILIATION_COMPLETED",
    "RECONCILE_POSITION_MISMATCH",
    "RECONCILE_BALANCE_MISMATCH",
    "RECONCILE_ORDER_PHANTOM",
    
    # Orchestrator
    "ORCH_STARTED",
    "ORCH_STOPPED",
    "ORCH_PAUSED",
    "ORCH_RESUMED",
    "ORCH_AUTO_PAUSED",
    "ORCH_AUTO_RESUMED",
    "ORCH_CYCLE_STARTED",
    "ORCH_CYCLE_COMPLETED",
    
    # Safety
    "DMS_ACTIVATED",
    "DMS_TRIGGERED",
    "DMS_SKIPPED",
    "DMS_PING",
    "EMERGENCY_STOP",
    "INSTANCE_LOCK_ACQUIRED",
    "INSTANCE_LOCK_FAILED",
    
    # Alerts
    "ALERT_SENT",
    "ALERT_CRITICAL",
    "ALERT_WARNING",
    "ALERT_INFO",
    "TELEGRAM_MESSAGE_SENT",
    
    # Errors
    "BROKER_ERROR",
    "STORAGE_ERROR",
    "API_ERROR",
    "NETWORK_ERROR",
    
    # Payload types
    "BaseEventPayload",
    "OrderPayload",
    "TradePayload",
    "SignalPayload",
    "RegimePayload",
    "RiskBlockedPayload",
    "PnLPayload",
    "PositionPayload",
    "HealthPayload",
    "AlertPayload",
    
    # Builders
    "build_order_event",
    "build_trade_event",
    "build_risk_blocked_event",
    "build_pnl_event",
    "build_regime_event",
    
    # Groups and helpers
    "TopicGroups",
    "is_valid_topic",
    "requires_notification",
    "is_critical",
]