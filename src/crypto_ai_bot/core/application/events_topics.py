from __future__ import annotations

# Единая точка истинных тем событий для всей системы

# Broker/orders
ORDER_EXECUTED = "order.executed"
ORDER_FAILED = "order.failed"

# Trade lifecycle
TRADE_COMPLETED = "trade.completed"
TRADE_FAILED = "trade.failed"
TRADE_SETTLED = "trade.settled"
TRADE_SETTLEMENT_TIMEOUT = "trade.settlement.timeout"
TRADE_BLOCKED = "trade.blocked"
TRADE_PARTIAL_FOLLOWUP = "trade.partial.followup"

# Health and monitoring
WATCHDOG_HEARTBEAT = "watchdog.heartbeat"
HEALTH_REPORT = "health.report"

# Risk and budgets
RISK_BLOCKED = "risk.blocked"
BUDGET_EXCEEDED = "budget.exceeded"

# Evaluation and decision
EVALUATION_STARTED = "evaluation.started"
DECISION_EVALUATED = "decision.evaluated"

# Reconciliation
RECONCILIATION_COMPLETED = "reconciliation.completed"
RECONCILE_POSITION_MISMATCH = "reconcile.position.mismatch"

# Orchestrator
ORCH_AUTO_PAUSED = "orch.auto.paused"
ORCH_AUTO_RESUMED = "orch.auto.resumed"

# Safety
DMS_TRIGGERED = "dms.triggered"
DMS_SKIPPED = "dms.skipped"

# Alertmanager (Prometheus/Grafana)
ALERTS_ALERTMANAGER = "alerts.alertmanager"

# Broker errors
BROKER_ERROR = "broker.error"
