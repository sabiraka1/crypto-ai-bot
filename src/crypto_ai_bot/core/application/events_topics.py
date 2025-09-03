from __future__ import annotations

# ДћвЂўДћВґДћВёДћВЅДћВ°Г‘ВЏ Г‘вЂљДћВѕГ‘вЂЎДћВєДћВ° ДћВёГ‘ВЃГ‘вЂљДћВёДћВЅДћВЅГ‘вЂ№ Г‘вЂљДћВµДћВјГ‘вЂ№ Гўв‚¬вЂќ ДћВёДћВјДћВїДћВѕГ‘в‚¬Г‘вЂљДћВёГ‘в‚¬Г‘Ж’ДћВµДћВј Г‘в‚¬ДћВµДћВµГ‘ВЃГ‘вЂљГ‘в‚¬ ДћВё ДћВїГ‘в‚¬ДћВѕДћВєДћВёДћВґГ‘вЂ№ДћВІДћВ°ДћВµДћВј ДћВєДћВѕДћВЅГ‘ВЃГ‘вЂљДћВ°ДћВЅГ‘вЂљГ‘вЂ№ ДћВЅДћВ°Г‘в‚¬Г‘Ж’ДћВ¶Г‘Ж’.
from crypto_ai_bot.core.application import events_topics as EVT  # noqa: N812

# ДћвЂГ‘в‚¬ДћВѕДћВєДћВµГ‘в‚¬/ДћВѕГ‘в‚¬ДћВґДћВµГ‘в‚¬ДћВ°
ORDER_EXECUTED = EVT.ORDER_EXECUTED
ORDER_FAILED = EVT.ORDER_FAILED

# ДћВўДћВѕГ‘в‚¬ДћВіДћВѕДћВІГ‘вЂ№ДћВ№ Г‘Л†ДћВ°ДћВі (high-level)
TRADE_COMPLETED = EVT.TRADE_COMPLETED
TRADE_FAILED = EVT.TRADE_FAILED
TRADE_SETTLED = EVT.TRADE_SETTLED
TRADE_SETTLEMENT_TIMEOUT = EVT.TRADE_SETTLEMENT_TIMEOUT
TRADE_BLOCKED = EVT.TRADE_BLOCKED
TRADE_PARTIAL_FOLLOWUP = EVT.TRADE_PARTIAL_FOLLOWUP

# ДћвЂ”ДћВґДћВѕГ‘в‚¬ДћВѕДћВІГ‘Е’ДћВµ ДћВё ДћВЅДћВ°ДћВ±ДћВ»Г‘ВЋДћВґДћВ°ДћВµДћВјДћВѕГ‘ВЃГ‘вЂљГ‘Е’
WATCHDOG_HEARTBEAT = EVT.WATCHDOG_HEARTBEAT
HEALTH_REPORT = EVT.HEALTH_REPORT

# ДћВ ДћВёГ‘ВЃДћВєДћВё/ДћВ±Г‘ВЋДћВґДћВ¶ДћВµГ‘вЂљГ‘вЂ№
RISK_BLOCKED = EVT.RISK_BLOCKED
BUDGET_EXCEEDED = EVT.BUDGET_EXCEEDED

# ДћВћГ‘вЂ ДћВµДћВЅДћВєДћВ°/Г‘в‚¬ДћВµГ‘Л†ДћВµДћВЅДћВёДћВµ (ДћВ»ДћВѕДћВєДћВ°ДћВ»Г‘Е’ДћВЅГ‘вЂ№ДћВµ Г‘в‚¬ДћВ°ДћВ±ДћВѕГ‘вЂЎДћВёДћВµ Г‘вЂљДћВµДћВјГ‘вЂ№)
EVALUATION_STARTED = "evaluation.started"
DECISION_EVALUATED = "decision.evaluated"

# ДћВЎДћВІДћВµГ‘в‚¬ДћВєДћВё
RECONCILIATION_COMPLETED = EVT.RECONCILIATION_COMPLETED
RECONCILE_POSITION_MISMATCH = EVT.RECONCILE_POSITION_MISMATCH

# ДћВћГ‘в‚¬ДћВєДћВµГ‘ВЃГ‘вЂљГ‘в‚¬ДћВ°Г‘вЂљДћВѕГ‘в‚¬
ORCH_AUTO_PAUSED = EVT.ORCH_AUTO_PAUSED
ORCH_AUTO_RESUMED = EVT.ORCH_AUTO_RESUMED

# Safety
DMS_TRIGGERED = EVT.DMS_TRIGGERED
DMS_SKIPPED = EVT.DMS_SKIPPED

# Alertmanager (Prometheus/Grafana)
ALERTS_ALERTMANAGER = EVT.ALERTS_ALERTMANAGER

# ДћВћГ‘Л†ДћВёДћВ±ДћВєДћВё ДћВ±Г‘в‚¬ДћВѕДћВєДћВµГ‘в‚¬ДћВ°
BROKER_ERROR = EVT.BROKER_ERROR
