# crypto-ai-bot

Long-only автотрейдинг криптовалют (Gate.io, расширяемо на другие биржи).  
Единый пайплайн: **evaluate → risk → place_order → protective_exits → reconcile → watchdog**.

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
Если cab-* команды не видны в PATH — запускайте через python -m crypto_ai_bot.cli.<cmd> (см. ниже).

2) Конфигурация
Скопируйте .env.example → .env и задайте переменные (режим, символ, лимиты, ключи для live).

Ключи можно передать безопасно:

API_KEY_FILE / API_SECRET_FILE (путь к файлу),

API_KEY_B64 / API_SECRET_B64 (base64),

SECRETS_FILE (JSON с ключами),

или просто API_KEY / API_SECRET.

3) Запуск сервера (локально)
bash
Копировать код
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000
Эндпойнты:

GET /health — сводное состояние,

GET /ready — готовность (200/503),

GET /metrics — Prometheus-текст (с JSON-фолбэком),

POST /orchestrator/start|stop, GET /orchestrator/status (при API_TOKEN — с Bearer auth).

4) Smoke/CLI (после pip install -e .)
bash
Копировать код
# Одноразовый прогон здоровья (внутренняя компоновка)
cab-smoke

# Обслуживание БД (backups/rotate/vacuum/integrity/list)
cab-maintenance backup
cab-maintenance rotate --days 30
cab-maintenance vacuum
cab-maintenance integrity
cab-maintenance list

# Сверки (orders/positions/balances) — единичный прогон
cab-reconcile

# Мониторинг health по HTTP (когда сервер запущен)
cab-health --oneshot --url http://127.0.0.1:8000/health

# Отчёт по сделкам/PNL за сегодня
cab-perf
Альтернатива без PATH:

bash
Копировать код
python -m crypto_ai_bot.app.e2e_smoke
python -m crypto_ai_bot.cli.maintenance backup
python -m crypto_ai_bot.cli.reconcile
python -m crypto_ai_bot.cli.health_monitor --oneshot --url http://127.0.0.1:8000/health
python -m crypto_ai_bot.cli.performance
🎛️ Режимы (одна логика везде)
PAPER: MODE=paper, PRICE_FEED=fixed|live, SANDBOX=0.
Симулятор с реальной логикой: идемпотентность, риски, защитные выходы, сверки — как в live.

LIVE-SANDBOX: MODE=live, SANDBOX=1 (если у биржи/CCXT есть тестнет).

LIVE (prod): MODE=live, SANDBOX=0.
Включаются InstanceLock и Dead Man’s Switch по умолчанию.

Переключение без смены кода — только ENV.

🔐 Безопасность и риски
Идемпотентность: bucket_ms + TTL (хранится в БД).

RiskManager: единый формат ответа {"ok": bool, "reasons": [...], "limits": {...}}.

cooldown per-symbol,

лимит спреда,

max position (base),

max orders/hour,

дневной loss-limit по quote.

Защитные выходы: ProtectiveExits (hard stop + trailing, per-settings).

Dead Man’s Switch + InstanceLock для live.

Token-auth для управляющих ручек (API_TOKEN).

🔄 Сверки (Reconciliation)
Оркестратор периодически запускает:

OrdersReconciler — открытые ордера (если брокер поддерживает fetch_open_orders).

PositionsReconciler — локальная позиция vs. биржевой баланс base.

BalancesReconciler — free-балансы base/quote по символу.

🗄️ База данных и обслуживание
SQLite, миграции при старте (compose.build_container вызывает run_migrations).
Обслуживание:

bash
Копировать код
cab-maintenance backup            # создать бэкап ./backups/db-YYYYmmdd-HHMMSS.sqlite3
cab-maintenance rotate --days 30  # удаление старых
cab-maintenance vacuum            # VACUUM + PRAGMA
cab-maintenance integrity         # PRAGMA integrity_check
📊 Наблюдаемость
GET /health, GET /ready — для Liveness/Readiness.

GET /metrics — Prometheus-совместимый текст (встроенный no-op сборщик, без внешних зависимостей).

Логи — структурные (JSON), сквозные поля для корреляции.

⚙️ Переменные окружения (ключевые)
Режим/Биржа

MODE=paper|live, SANDBOX=0|1, EXCHANGE=gateio

SYMBOL=BTC/USDT (мультисимвол опционален через SYMBOLS)

Торговля

FIXED_AMOUNT (Decimal, quote)

PRICE_FEED=fixed|live, FIXED_PRICE (для PRICE_FEED=fixed)

Риски / Идемпотентность

RISK_COOLDOWN_SEC, RISK_MAX_SPREAD_PCT, RISK_MAX_POSITION_BASE,
RISK_MAX_ORDERS_PER_HOUR, RISK_DAILY_LOSS_LIMIT_QUOTE

IDEMPOTENCY_BUCKET_MS, IDEMPOTENCY_TTL_SEC

Оркестратор

EVAL_INTERVAL_SEC, EXITS_INTERVAL_SEC,
RECONCILE_INTERVAL_SEC, WATCHDOG_INTERVAL_SEC, DMS_TIMEOUT_MS

Хранилище/Сервис

DB_PATH, BACKUP_RETENTION_DAYS, LOG_LEVEL, API_TOKEN

Ключи (любой из вариантов)

API_KEY / API_SECRET

API_KEY_FILE / API_SECRET_FILE

API_KEY_B64 / API_SECRET_B64

SECRETS_FILE (JSON)

🧱 Архитектура и слои
Слои: cli, app → core → utils.

Импорты только пакетные: from crypto_ai_bot.utils.time import now_ms

ENV читаем ТОЛЬКО в core/settings.py.

Денежные величины — Decimal.

Брокеры: PaperBroker (симулятор), CcxtBroker (live/sandbox).

Нет core/brokers/live.py — все live-операции обеспечивает CcxtBroker.

Import-Linter контролирует слои (cli/app не импортируются из core/utils и т.д.).

📦 Структура проекта (актуальная)
bash
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
├─ .github/workflows/ci.yml
├─ ops/prometheus/
│  ├─ alerts.yml
│  ├─ alertmanager.yml
│  ├─ prometheus.yml
│  └─ docker-compose.yml
└─ src/crypto_ai_bot/
   ├─ app/
   │  ├─ server.py
   │  └─ compose.py
   ├─ cli/
   │  ├─ __init__.py
   │  ├─ maintenance.py
   │  ├─ reconcile.py
   │  ├─ health_monitor.py
   │  └─ performance.py
   ├─ core/
   │  ├─ settings.py
   │  ├─ orchestrator.py
   │  ├─ events/{bus.py,topics.py}
   │  ├─ brokers/{base.py,ccxt_adapter.py,paper.py,symbols.py}
   │  ├─ risk/{manager.py,protective_exits.py}
   │  ├─ reconciliation/{orders.py,positions.py,balances.py}
   │  ├─ safety/{dead_mans_switch.py,instance_lock.py}
   │  ├─ monitoring/health_checker.py
   │  └─ storage/
   │     ├─ facade.py
   │     ├─ migrations/{runner.py,cli.py}
   │     └─ repositories/{trades.py,positions.py,market_data.py,audit.py,idempotency.py}
   └─ utils/
      ├─ __init__.py
      ├─ time.py, ids.py, logging.py, metrics.py
      ├─ retry.py, circuit_breaker.py
      ├─ exceptions.py
      └─ http_client.py
⚠️ Дисклеймер
Торговля криптовалютой связана с риском. Используете на свой страх и риск.