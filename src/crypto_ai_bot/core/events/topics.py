from __future__ import annotations


class Topics:
    """Список констант топиков событий (минимально достаточный)."""
    DECISION_EVALUATED = "decision.evaluated"
    ORDER_EXECUTED = "order.executed"
    ORDER_FAILED = "order.failed"
    POSITION_CHANGED = "position.changed"
    RISK_BLOCKED = "risk.blocked"
    PROTECTIVE_EXIT_TRIGGERED = "protective_exit.triggered" 