# crypto-ai-bot

Long-only автотрейдинг криптовалют (Gate.io через CCXT).  
**Единая логика** для paper и live: `evaluate → risk → execute_trade → protective_exits → reconcile → watchdog`.

---

## ⚡ Быстрый старт

### 1) Установка
```bash
python -m venv .venv
# Windows (PowerShell): .\.venv\Scripts\Activate.ps1
# Windows (Git Bash):   source .venv/Scripts/activate
# Linux/macOS:          source .venv/bin/activate

pip install -U pip wheel
pip install -e .
2) Конфигурация
Скопируйте .env.example → .env и задайте переменные (режим, символ, лимиты, ключи для live).

Ключи можно задавать безопасно (любой вариант):

API_KEY_FILE / API_SECRET_FILE — путь к файлу с ключом

API_KEY_B64 / API_SECRET_B64 — base64-значения

SECRETS_FILE — JSON с ключами

или просто API_KEY / API_SECRET

3) Запуск сервера (локально)
bash
Копировать код
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000
Эндпойнты:

GET /health — сводное состояние

GET /ready — готовность (200/503)

GET /metrics — метрики Prometheus (встроенный no-op сборщик)

POST /orchestrator/start|stop, GET /orchestrator/status (при API_TOKEN — Bearer auth)

4) CLI (после pip install -e .)
bash
Копировать код
# Одноразовый прогон здоровья сборки
cab-smoke

# Обслуживание БД (backups/rotate/vacuum/integrity/list)
cab-maintenance backup
cab-maintenance rotate --days 30
cab-maintenance vacuum
cab-maintenance integrity
cab-maintenance list

# Сверки (orders/positions/balances)
cab-reconcile

# Мониторинг health по HTTP (когда сервер запущен)
cab-health --oneshot --url http://127.0.0.1:8000/health

# Отчёт по сделкам/PNL за сегодня
cab-perf
Альтернатива без PATH:

bash
Копировать код
python -m crypto_ai_bot.cli.smoke
python -m crypto_ai_bot.cli.maintenance backup
python -m crypto_ai_bot.cli.reconcile
python -m crypto_ai_bot.cli.health_monitor --oneshot --url http://127.0.0.1:8000/health
python -m crypto_ai_bot.cli.performance
🎛️ Режимы (одна логика везде)
PAPER: MODE=paper. Cимулятор с реальной логикой: идемпотентность, риски, защитные выходы, сверки — как в live.

LIVE: MODE=live. Реальные ордера через CCXT. (Отдельного spot-sandbox у Gate.io нет, поэтому аккуратный лайв — с малыми лимитами/саб-аккаунтом.)

Переключение режимов — только ENV, код один и тот же.

🔐 Безопасность и риски
Идемпотентность: bucket_ms + TTL (ключи хранятся в БД).

RiskManager (check → {"ok": bool, "reasons": [...], "limits": {...}}): cooldown per-symbol, лимит спреда, max position (base), max orders/hour, дневной loss-limit по quote.

ProtectiveExits: hard stop + trailing (per-settings).

Live-only: Dead Man’s Switch + InstanceLock.

Управляющие ручки: только по API_TOKEN (Bearer).

🔄 Сверки (Reconciliation)
Оркестратор периодически запускает:

OrdersReconciler — открытые ордера (если брокер поддерживает fetch_open_orders)

PositionsReconciler — локальная позиция vs. биржевой баланс base

BalancesReconciler — свободные base/quote по символу

🗄️ База данных и обслуживание
SQLite, миграции применяются при старте (migrations/runner.py).
Обслуживание:

bash
Копировать код
cab-maintenance backup            # ./backups/db-YYYYmmdd-HHMMSS.sqlite3
cab-maintenance rotate --days 30  # удаление старых
cab-maintenance vacuum            # VACUUM + PRAGMA
cab-maintenance integrity         # PRAGMA integrity_check
📊 Наблюдаемость
GET /health, GET /ready — liveness/readiness

GET /metrics — Prometheus-текст (встроенный, не требует внешних либ)

Логи — структурные (JSON), поля корреляции

Telegram-алерты: в app/compose.py встроен подписчик шины (trade.completed/blocked/failed, watchdog.heartbeat). При пустых TELEGRAM_* — no-op.

⚙️ ENV (ключевые)
Режим/Биржа

ini
Копировать код
MODE=paper|live
EXCHANGE=gateio
SYMBOL=BTC/USDT
Торговля/Риски

ini
Копировать код
FIXED_AMOUNT=25
FEE_PCT_ESTIMATE=0.001
RISK_COOLDOWN_SEC=0
RISK_MAX_SPREAD_PCT=0.005
RISK_MAX_POSITION_BASE=0
RISK_MAX_ORDERS_PER_HOUR=10
RISK_DAILY_LOSS_LIMIT_QUOTE=50
RISK_MAX_FEE_PCT=0.002
RISK_MAX_SLIPPAGE_PCT=0.01
IDEMPOTENCY_BUCKET_MS=60000
IDEMPOTENCY_TTL_SEC=120
EVAL_INTERVAL_SEC=3
EXITS_INTERVAL_SEC=5
RECONCILE_INTERVAL_SEC=10
WATCHDOG_INTERVAL_SEC=3
DMS_TIMEOUT_MS=120000
Ключи (любой из вариантов)

java
Копировать код
API_KEY / API_SECRET
API_KEY_FILE / API_SECRET_FILE
API_KEY_B64 / API_SECRET_B64
SECRETS_FILE (JSON)
Telegram (если нужны алерты)

nginx
Копировать код
TELEGRAM_BOT_TOKEN / TELEGRAM_BOT_TOKEN_B64
TELEGRAM_BOT_SECRET / TELEGRAM_BOT_SECRET_B64
TELEGRAM_CHAT_ID
Хранилище/Сервис

ini
Копировать код
DB_PATH=/data/crypto_ai_bot.db
HTTP_TIMEOUT_SEC=30
LOG_LEVEL=INFO
🧱 Архитектура и инварианты
Слои

pgsql
Копировать код
app/  →  core (application → domain → infrastructure)  →  utils/
ENV читаем только в core/infrastructure/settings.py

Денежные величины — Decimal; внешние значения через utils.decimal.dec(...)

Брокеры: PaperBroker (симулятор), CcxtBroker (live)

Import-Linter контролирует слои

Единый IBroker

fetch_ticker(symbol) -> TickerDTO

fetch_balance(symbol) -> BalanceDTO(free_quote, free_base)

create_market_buy_quote(...), create_market_sell_base(...)

Gate.io / CCXT

Нормализация символов, precision/limits, квантование, rate-limit / circuit-breaker / retry

📦 Структура (финальная)
pgsql
Копировать код
crypto-ai-bot/
├─ README.md
├─ pyproject.toml
├─ requirements.txt
├─ requirements-dev.txt
├─ .env.example
├─ .gitignore
├─ Makefile
├─ Procfile
├─ pytest.ini
├─ importlinter.ini
├─ ops/prometheus/{alerts.yml,alertmanager.yml,prometheus.yml,docker-compose.yml}
├─ scripts/{README.md,backup_db.py,rotate_backups.py,integrity_check.py,run_server.sh,run_server.ps1}
└─ src/crypto_ai_bot/
   ├─ app/{server.py,compose.py,adapters/telegram.py}
   ├─ cli/{__init__.py,smoke.py,maintenance.py,reconcile.py,health_monitor.py,performance.py}
   ├─ core/
   │  ├─ application/
   │  │  ├─ orchestrator.py
   │  │  ├─ protective_exits.py
   │  │  ├─ use_cases/{eval_and_execute.py,execute_trade.py,place_order.py,partial_fills.py}
   │  │  ├─ reconciliation/{orders.py,positions.py,balances.py}
   │  │  └─ monitoring/{health_checker.py,dlq_subscriber.py}
   │  ├─ domain/
   │  │  ├─ risk/{manager.py,rules/{loss_streak.py,max_drawdown.py}}
   │  │  ├─ strategies/
   │  │  ├─ indicators/
   │  │  └─ signals/
   │  └─ infrastructure/
   │     ├─ settings.py
   │     ├─ events/{bus.py,topics.py}
   │     ├─ brokers/{base.py,ccxt_adapter.py,paper.py,symbols.py}
   │     ├─ storage/
   │     │  ├─ facade.py, sqlite_adapter.py, backup.py
   │     │  ├─ migrations/{runner.py,V0001__init.sql,V0002__trades_fee_partial.sql,V0003__audit_idempotency.sql,V0004__safety_and_recon.sql,V0005__schema_fixes.sql}
   │     │  └─ repositories/{trades.py,positions.py,market_data.py,audit.py,idempotency.py}
   │     └─ safety/{dead_mans_switch.py,instance_lock.py}
   ├─ alerts/{reconcile_stale.py}
   ├─ analytics/{metrics.py,pnl.py}
   ├─ validators/{settings.py,dto.py}
   └─ utils/{__init__.py,time.py,ids.py,logging.py,metrics.py,decimal.py,retry.py,cir