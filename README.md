Long-only автотрейдинг криптовалют (основа: Gate.io; архитектура расширяема на другие биржи).  
Единый пайплайн исполнения: **evaluate → risk → place_order → protective_exits → reconcile → watchdog**.  
Слои: `utils → core → app`. Брокеры через общий интерфейс `IBroker`.

---

## ⚡ Быстрый старт

### 1) Установка
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip wheel
pip install -e .
2) Минимальная конфигурация .env
env
Копировать
Редактировать
# режим и биржа
MODE=paper                 # paper | live
SANDBOX=0                  # для live: 1=тестнет (если биржа поддерживает), 0=прод

EXCHANGE=gateio
SYMBOL=BTC/USDT
FIXED_AMOUNT=50            # размер покупки в QUOTE за тик

# база данных и идемпотентность
DB_PATH=./data/trader.sqlite3
IDEMPOTENCY_BUCKET_MS=60000
IDEMPOTENCY_TTL_SEC=3600

# риск-лимиты (примерные)
RISK_COOLDOWN_SEC=60
RISK_MAX_SPREAD_PCT=0.3
RISK_MAX_POSITION_BASE=0.02
RISK_MAX_ORDERS_PER_HOUR=6
RISK_DAILY_LOSS_LIMIT_QUOTE=100

# ключи нужны только для live
API_KEY=
API_SECRET=
3) Smoke-проверки (безопасно)
bash
Копировать
Редактировать
# Комплексный health-check
python - <<'PY'
from crypto_ai_bot.app.compose import build_container
import asyncio
c = build_container()
async def main():
    rep = await c.health.check(symbol=c.settings.SYMBOL)
    print("MODE=", c.settings.MODE, "SANDBOX=", c.settings.SANDBOX, "health_ok=", rep.ok, rep.details)
asyncio.run(main())
PY

# Один форс-тик оркестратора в paper (без реальных денег)
python - <<'PY'
from crypto_ai_bot.app.compose import build_container
import asyncio
c = build_container()
c.orchestrator.force_eval_action = "buy"
async def main():
    c.orchestrator.start()
    await asyncio.sleep(1.0)
    await c.orchestrator.stop()
    print("done")
asyncio.run(main())
PY
🎛️ Режимы работы (одна логика)
Полностью безопасный тест (симулятор):

env
Копировать
Редактировать
MODE=paper
SANDBOX=0
Используется PaperBroker (встроенный симулятор). По умолчанию цена безопасная фиксированная; при необходимости можно подать «живой» фид цены (см. обсуждение в issues/PR).

Тестнет биржи (если доступен в CCXT):

env
Копировать
Редактировать
MODE=live
SANDBOX=1
API_KEY=...   # тестовые ключи
API_SECRET=...
Тот же код, но запросы идут в песочницу биржи (деньги ненастоящие).

Боевой live:

env
Копировать
Редактировать
MODE=live
SANDBOX=0
API_KEY=...   # прод-ключи (желательно с IP whitelist)
API_SECRET=...
Интервалы оркестратора (по спецификации и коду):
eval=60s, exits=5s, reconcile=60s, watchdog=15s.

Рекомендация: использовать разные файлы БД для разных сред (paper / live-sandbox / live-prod), чтобы не смешивать данные.

🔐 Безопасность и управление рисками
Идемпотентность ордеров (bucket + TTL) — защита от дублей при сетевых/повторных вызовах.

Instance Lock — исключает двойной запуск в live.

Dead Man’s Switch — сторож: при отсутствии heartbeat закрывает позиции.

Protective Exits — защитные выходы, если позиция открыта и условия сработали.

Риск-менеджер: кулдаун, лимит спреда, лимит размера позиции/частоты сделок, дневной loss-limit.

🔄 Сверки / Reconciliation
Компоненты сверок запускаются из оркестратора:

OrdersReconciler — висящие/незакрытые ордера;

PositionsReconciler — локальная позиция vs. биржевой баланс (через BalanceDTO);

BalancesReconciler — диагностика free-балансов по символу.

Ручной запуск (CLI):

bash
Копировать
Редактировать
python -m scripts.reconciler --format text
python -m scripts.reconciler --check-only --format json
🛠️ Утилиты (CLI)
scripts/maintenance_cli.py — бэкапы/ротация/вакуум/интегрити:

bash
Копировать
Редактировать
python -m scripts.maintenance_cli backup-db --compress --retention-days 14
python -m scripts.maintenance_cli prune-backups --retention-days 7
python -m scripts.maintenance_cli cleanup --what idempotency --days 3
python -m scripts.maintenance_cli vacuum
python -m scripts.maintenance_cli stats
python -m scripts.maintenance_cli integrity
scripts/health_monitor.py — монитор /health + оповещения в Telegram:

bash
Копировать
Редактировать
python -m scripts.health_monitor check --url http://localhost:8000/health
python -m scripts.health_monitor watch --url http://localhost:8000/health --interval 30 \
  --telegram-bot-token "$TELEGRAM_BOT_TOKEN" --telegram-chat-id "$TELEGRAM_ALERT_CHAT_ID"
scripts/performance_report.py — FIFO-PnL, win-rate, max drawdown:

bash
Копировать
Редактировать
python -m scripts.performance_report --symbol BTC/USDT --since 2025-01-01T00:00:00 --format json
python -m scripts.performance_report --end-price 68000 --format text
🧱 Архитектура (вкратце)
core.brokers — IBroker, PaperBroker (симулятор), CcxtBroker (live/sandbox).

core.use_cases — evaluate, eval_and_execute, place_order (идемпотентность).

core.risk — RiskManager, ProtectiveExits.

core.reconciliation — сверки Orders/Positions/Balances.

core.monitoring — HealthChecker.

core.storage — миграции, фасад, репозитории (SQLite).

app.compose — сборка контейнера (DI), выбор брокера, запуск оркестратора.

Мы не используем core/brokers/live.py (удалён как дублирующий CcxtBroker).

📊 Наблюдаемость и бэкапы
Health: общий чек состояния (БД, брокер, шина и т.д.).

Метрики: счётчики решений/блокировок/времени операций (для экспорта в Prometheus — по желанию).

Резервные копии БД и очистка: через maintenance_cli.py (см. выше).

Если применяешь Prometheus/Grafana — держи в ops/ свой docker-compose.yml, prometheus.yml, алерты и т.п. (в проекте уже есть примеры файлов).

⚙️ Переменные окружения (полный список)
Var	Назначение	Пример	Примечание
MODE	Режим	paper | live	
SANDBOX	Тестнет	0/1	Только для live
EXCHANGE	CCXT ID	gateio	
SYMBOL	Торговая пара	BTC/USDT	
FIXED_AMOUNT	Сумма покупки в QUOTE	50	На один тик buy
DB_PATH	Путь к SQLite	./data/trader.sqlite3	Рекомендуется разделять по средам
API_KEY, API_SECRET	Ключи биржи		Только для live
RISK_COOLDOWN_SEC	Кулдаун	60	
RISK_MAX_SPREAD_PCT	Макс. спред, %	0.3	
RISK_MAX_POSITION_BASE	Макс. позиция (base)	0.02	
RISK_MAX_ORDERS_PER_HOUR	Частота	6	
RISK_DAILY_LOSS_LIMIT_QUOTE	Дневной лимит убытка	100	
IDEMPOTENCY_BUCKET_MS	Окно идемпотентности	60000	
IDEMPOTENCY_TTL_SEC	TTL ключей	3600	

🚀 Railway: профили окружения (Variables)
PAPER (полностью безопасно)

ini
Копировать
Редактировать
MODE=paper
SANDBOX=0
EXCHANGE=gateio
SYMBOL=BTC/USDT
FIXED_AMOUNT=50
DB_PATH=./data/trader-paper.sqlite3
IDEMPOTENCY_BUCKET_MS=60000
IDEMPOTENCY_TTL_SEC=3600
RISK_COOLDOWN_SEC=60
RISK_MAX_SPREAD_PCT=0.3
RISK_MAX_POSITION_BASE=0.02
RISK_MAX_ORDERS_PER_HOUR=6
RISK_DAILY_LOSS_LIMIT_QUOTE=100
LIVE-SANDBOX (тестовые ключи, при наличии тестнета у биржи)

ini
Копировать
Редактировать
MODE=live
SANDBOX=1
EXCHANGE=gateio
SYMBOL=BTC/USDT
FIXED_AMOUNT=5
DB_PATH=./data/trader-live-sandbox.sqlite3
API_KEY=...
API_SECRET=...
# те же risk/idem значения, можно ужесточить
LIVE-PROD (боевые ключи)

ini
Копировать
Редактировать
MODE=live
SANDBOX=0
EXCHANGE=gateio
SYMBOL=BTC/USDT
FIXED_AMOUNT=5
DB_PATH=./data/trader-live.sqlite3
API_KEY=...
API_SECRET=...
# рекомендую консервативные risk-параметры
🧭 Карта функций (кто за что отвечает)
core/use_cases/eval_and_execute.py — единый шаг исполения (evaluate → risk → place → exits → publish).

core/brokers/paper.py — симулятор ордеров, комиссии, спред.

core/brokers/ccxt_adapter.py — live/тестнет через CCXT (precision/limits/rounding, open_orders).

core/risk/manager.py — кулдауны, лимиты частоты/спреда/размера, дневной loss-limit.

core/risk/protective_exits.py — защитные выходы.

core/reconciliation/* — сверки ордеров/позиций/балансов.

core/monitoring/health_checker.py — комплексный health.

scripts/* — обслуживание БД, сверки, мониторинг, перф-отчёты.

⚠️ Дисклеймер
Торговля криптовалютой связана с риском. Вы используете проект на свой страх и риск. Автор(ы) не несут ответственности за возможные финансовые потери.