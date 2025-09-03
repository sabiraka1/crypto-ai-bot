from __future__ import annotations

# Ğ•Ğ´Ğ¸Ğ½Ğ°Ñ Ñ‚Ğ¾Ñ‡ĞºĞ° Ğ¸ÑÑ‚Ğ¸Ğ½Ğ½Ñ‹ Ñ‚ĞµĞ¼Ñ‹ â€” Ğ¸Ğ¼Ğ¿Ğ¾Ñ€Ñ‚Ğ¸Ñ€ÑƒĞµĞ¼ Ñ€ĞµĞµÑÑ‚Ñ€ Ğ¸ Ğ¿Ñ€Ğ¾ĞºĞ¸Ğ´Ñ‹Ğ²Ğ°ĞµĞ¼ ĞºĞ¾Ğ½ÑÑ‚Ğ°Ğ½Ñ‚Ñ‹ Ğ½Ğ°Ñ€ÑƒĞ¶Ñƒ.
from crypto_ai_bot.core.application import events_topics as EVT  # noqa: N812

# Ğ‘Ñ€Ğ¾ĞºĞµÑ€/Ğ¾Ñ€Ğ´ĞµÑ€Ğ°
ORDER_EXECUTED = EVT.ORDER_EXECUTED
ORDER_FAILED = EVT.ORDER_FAILED

# Ğ¢Ğ¾Ñ€Ğ³Ğ¾Ğ²Ñ‹Ğ¹ ÑˆĞ°Ğ³ (high-level)
TRADE_COMPLETED = EVT.TRADE_COMPLETED
TRADE_FAILED = EVT.TRADE_FAILED
TRADE_SETTLED = EVT.TRADE_SETTLED
TRADE_SETTLEMENT_TIMEOUT = EVT.TRADE_SETTLEMENT_TIMEOUT
TRADE_BLOCKED = EVT.TRADE_BLOCKED
TRADE_PARTIAL_FOLLOWUP = EVT.TRADE_PARTIAL_FOLLOWUP

# Ğ—Ğ´Ğ¾Ñ€Ğ¾Ğ²ÑŒĞµ Ğ¸ Ğ½Ğ°Ğ±Ğ»ÑĞ´Ğ°ĞµĞ¼Ğ¾ÑÑ‚ÑŒ
WATCHDOG_HEARTBEAT = EVT.WATCHDOG_HEARTBEAT
HEALTH_REPORT = EVT.HEALTH_REPORT

# Ğ Ğ¸ÑĞºĞ¸/Ğ±ÑĞ´Ğ¶ĞµÑ‚Ñ‹
RISK_BLOCKED = EVT.RISK_BLOCKED
BUDGET_EXCEEDED = EVT.BUDGET_EXCEEDED

# ĞÑ†ĞµĞ½ĞºĞ°/Ñ€ĞµÑˆĞµĞ½Ğ¸Ğµ (Ğ»Ğ¾ĞºĞ°Ğ»ÑŒĞ½Ñ‹Ğµ Ñ€Ğ°Ğ±Ğ¾Ñ‡Ğ¸Ğµ Ñ‚ĞµĞ¼Ñ‹)
EVALUATION_STARTED = "evaluation.started"
DECISION_EVALUATED = "decision.evaluated"

# Ğ¡Ğ²ĞµÑ€ĞºĞ¸
RECONCILIATION_COMPLETED = EVT.RECONCILIATION_COMPLETED
RECONCILE_POSITION_MISMATCH = EVT.RECONCILE_POSITION_MISMATCH

# ĞÑ€ĞºĞµÑÑ‚Ñ€Ğ°Ñ‚Ğ¾Ñ€
ORCH_AUTO_PAUSED = EVT.ORCH_AUTO_PAUSED
ORCH_AUTO_RESUMED = EVT.ORCH_AUTO_RESUMED

# Safety
DMS_TRIGGERED = EVT.DMS_TRIGGERED
DMS_SKIPPED = EVT.DMS_SKIPPED

# Alertmanager (Prometheus/Grafana)
ALERTS_ALERTMANAGER = EVT.ALERTS_ALERTMANAGER

# ĞÑˆĞ¸Ğ±ĞºĞ¸ Ğ±Ñ€Ğ¾ĞºĞµÑ€Ğ°
BROKER_ERROR = EVT.BROKER_ERROR
