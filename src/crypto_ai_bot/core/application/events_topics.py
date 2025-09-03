# События (единый реестр тем шины)

# Брокер/ордера
ORDER_EXECUTED = "order.executed"
ORDER_FAILED = "order.failed"

# Торговый шаг (high-level)
TRADE_COMPLETED = "trade.completed"
TRADE_FAILED = "trade.failed"
TRADE_SETTLED = "trade.settled"
TRADE_SETTLEMENT_TIMEOUT = "trade.settlement_timeout"
TRADE_BLOCKED = "trade.blocked"
TRADE_PARTIAL_FOLLOWUP = "trade.partial_followup"  # <-- добавлено

# Здоровье и наблюдаемость
WATCHDOG_HEARTBEAT = "watchdog.heartbeat"
HEALTH_REPORT = "health.report"

# Риски/бюджеты
RISK_BLOCKED = "risk.blocked"
BUDGET_EXCEEDED = "budget.exceeded"

# Оценка/решение
EVALUATION_STARTED = "evaluation.started"
DECISION_EVALUATED = "decision.evaluated"

# Сверки
RECONCILIATION_COMPLETED = "reconciliation.completed"
RECONCILE_POSITION_MISMATCH = "reconcile.position_mismatch"

# Оркестратор
ORCH_AUTO_PAUSED = "orchestrator.auto_paused"
ORCH_AUTO_RESUMED = "orchestrator.auto_resumed"

# Safety
DMS_TRIGGERED = "safety.dms.triggered"
DMS_SKIPPED = "safety.dms.skipped"

# Alertmanager (Prometheus/Grafana)
ALERTS_ALERTMANAGER = "alerts.alertmanager"

# Ошибки брокера
BROKER_ERROR = "broker.error"
