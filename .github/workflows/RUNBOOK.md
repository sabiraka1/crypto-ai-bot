# Runbook — crypto-ai-bot

## Старт
- `MODE=paper` — локальный прогон без реальной торговли.
- `MODE=live` — реальная торговля, обязателен `API_TOKEN` при `REQUIRE_API_TOKEN_IN_LIVE=1`.
- Эндпоинты: `/live`, `/ready`, `/metrics`, `/orchestrator/*`, `/trade/force`.

## Переменные безопасности
- **Budget** (глобал): `BUDGET_MAX_ORDERS_5M`, `BUDGET_MAX_TURNOVER_DAY_QUOTE`
- **Budget** (per-symbol): `BUDGET_MAX_ORDERS_5M_<BASE>_<QUOTE>`, `BUDGET_MAX_TURNOVER_DAY_QUOTE_<BASE>_<QUOTE>`
- **Risk** (глобал): `MAX_POSITION_BASE`, `MAX_LOSS_DAY_QUOTE`, `COOLDOWN_AFTER_LOSS_MIN`
- **Risk** (per-symbol): `MAX_POSITION_BASE_<B>_<Q>`, `MAX_LOSS_DAY_QUOTE_<B>_<Q>`, `COOLDOWN_AFTER_LOSS_MIN_<B>_<Q>`
- **DMS**: `DMS_TIMEOUT_MS`, `DMS_RECHECKS`, `DMS_RECHECK_DELAY_SEC`, `DMS_MAX_IMPACT_PCT`

## Обычные операции
- Автопауза: срабатывает по budget или SLA. Снять — `/orchestrator/resume` (или дождаться авто-resume).
- Reconcile: включён по умолчанию, авто-фиксация при `RECONCILE_AUTOFIX=1`.
- Проверка готовности: `GET /ready` (вернёт 503 с причиной, если стартовая сверка не прошла).

## Инциденты
- Много `budget_exceeded` → проверь лимиты и частоту сигналов стратегии.
- `dms_trigger_total` > 0 → проверь сетевые проблемы/латентность и логи брокера.
- Несоответствие позиции — см. алёрты `reconcile.position_mismatch`.
