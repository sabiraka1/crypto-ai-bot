"""
Event topics registry for the crypto trading system.

This module defines all event topics used across the application.
It serves as the single source of truth for event names.
"""

from __future__ import annotations

from typing import Final

# ============================================================================
# BROKER & ORDERS
# ============================================================================

ORDER_EXECUTED: Final[str] = "order.executed"
ORDER_FAILED: Final[str] = "order.failed"

# ============================================================================
# TRADE LIFECYCLE
# ============================================================================

TRADE_COMPLETED: Final[str] = "trade.completed"
TRADE_FAILED: Final[str] = "trade.failed"
TRADE_SETTLED: Final[str] = "trade.settled"
TRADE_SETTLEMENT_TIMEOUT: Final[str] = "trade.settlement.timeout"
TRADE_BLOCKED: Final[str] = "trade.blocked"
TRADE_PARTIAL_FOLLOWUP: Final[str] = "trade.partial.followup"

# ============================================================================
# HEALTH & MONITORING
# ============================================================================

WATCHDOG_HEARTBEAT: Final[str] = "watchdog.heartbeat"
HEALTH_REPORT: Final[str] = "health.report"

# ============================================================================
# RISK & BUDGETS
# ============================================================================

RISK_BLOCKED: Final[str] = "risk.blocked"
BUDGET_EXCEEDED: Final[str] = "budget.exceeded"

# ============================================================================
# EVALUATION & DECISION
# ============================================================================

EVALUATION_STARTED: Final[str] = "evaluation.started"
DECISION_EVALUATED: Final[str] = "decision.evaluated"

# ============================================================================
# RECONCILIATION
# ============================================================================

RECONCILIATION_COMPLETED: Final[str] = "reconciliation.completed"
RECONCILE_POSITION_MISMATCH: Final[str] = "reconcile.position.mismatch"

# ============================================================================
# ORCHESTRATOR
# ============================================================================

ORCH_AUTO_PAUSED: Final[str] = "orch.auto.paused"
ORCH_AUTO_RESUMED: Final[str] = "orch.auto.resumed"

# ============================================================================
# SAFETY
# ============================================================================

DMS_TRIGGERED: Final[str] = "dms.triggered"
DMS_SKIPPED: Final[str] = "dms.skipped"

# ============================================================================
# ALERTING
# ============================================================================

ALERTS_ALERTMANAGER: Final[str] = "alerts.alertmanager"

# ============================================================================
# BROKER ERRORS
# ============================================================================

BROKER_ERROR: Final[str] = "broker.error"

# ============================================================================
# TOPIC GROUPS (for easier management)
# ============================================================================


class TopicGroups:
    """Grouped event topics for easier access."""

    ORDERS = [ORDER_EXECUTED, ORDER_FAILED]

    TRADES = [
        TRADE_COMPLETED,
        TRADE_FAILED,
        TRADE_SETTLED,
        TRADE_SETTLEMENT_TIMEOUT,
        TRADE_BLOCKED,
        TRADE_PARTIAL_FOLLOWUP,
    ]

    HEALTH = [WATCHDOG_HEARTBEAT, HEALTH_REPORT]

    RISK = [RISK_BLOCKED, BUDGET_EXCEEDED]

    EVALUATION = [EVALUATION_STARTED, DECISION_EVALUATED]

    RECONCILIATION = [RECONCILIATION_COMPLETED, RECONCILE_POSITION_MISMATCH]

    ORCHESTRATOR = [ORCH_AUTO_PAUSED, ORCH_AUTO_RESUMED]

    SAFETY = [DMS_TRIGGERED, DMS_SKIPPED]

    ALERTS = [ALERTS_ALERTMANAGER]

    ERRORS = [BROKER_ERROR]

    @classmethod
    def all_topics(cls) -> list[str]:
        """Get all defined topics."""
        topics = []
        for attr_name in dir(cls):
            if not attr_name.startswith("_") and attr_name.isupper():
                attr = getattr(cls, attr_name)
                if isinstance(attr, list):
                    topics.extend(attr)
        return topics


def is_valid_topic(topic: str) -> bool:
    """Check if a topic is valid."""
    return topic in TopicGroups.all_topics()
