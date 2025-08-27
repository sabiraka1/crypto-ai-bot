# crypto-ai-bot

Long-only автотрейдинг криптовалют (Gate.io через CCXT).  
**Единая логика** для paper и live режимов: evaluate → risk → place_order → protective_exits → reconcile → watchdog.

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

POST /orchestrator/start|stop, GET /orchestrator/status (при API_TOKEN — через Bearer auth)

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
PAPER: MODE=paper, PRICE_FEED=fixed|live, SANDBOX=0.
Симулятор с реальной логикой: идемпотентность, риски, защитные выходы, сверки — как в live.

LIVE-SANDBOX: MODE=live, SANDBOX=1 (если CCXT/биржа поддерживает тестнет).

LIVE (prod): MODE=live, SANDBOX=0.
Включаются InstanceLock и Dead Man’s Switch по умолчанию.

Переключение без смены кода — только ENV.

🔐 Безопасность и риски
Идемпотентность: bucket_ms + TTL (ключи хранятся в БД).

RiskManager (единый формат):
{"ok": bool, "reasons": [...], "limits": {...}}
Включает: cooldown per-symbol, лимит спреда, max position (base), max orders/hour, дневной loss-limit по quote.

ProtectiveExits: hard stop + trailing (per-settings).

Live-only: Dead Man’s Switch + InstanceLock.

Управляющие ручки: только по API_TOKEN (Bearer).

🔄 Сверки (Reconciliation)
Оркестратор периодически запускает:

OrdersReconciler — открытые ордера (если брокер поддерживает fetch_open_orders),

PositionsReconciler — локальная позиция vs. биржевой баланс base,

BalancesReconciler — свободные base/quote по символу.

🗄️ База данных и обслуживание
SQLite, миграции при старте (compose.build_container вызывает run_migrations).
Обслуживание:

bash
Копировать код
cab-maintenance backup            # ./backups/db-YYYYmmdd-HHMMSS.sqlite3
cab-maintenance rotate --days 30  # удаление старых
cab-maintenance vacuum            # VACUUM + PRAGMA
cab-maintenance integrity         # PRAGMA integrity_check
📊 Наблюдаемость
GET /health, GET /ready — liveness/readiness.

GET /metrics — Prometheus-текст (встроенный, не требует внешних либ).

Логи — структурные (JSON), поля корреляции.

⚙️ Переменные окружения (ключевые)
Режим/Биржа

MODE=paper|live, SANDBOX=0|1, EXCHANGE=gateio

SYMBOL=BTC/USDT (мультисимвол опционально через SYMBOLS)

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

🧱 Архитектура и инварианты
Слои и зависимости

Копировать код
app/  →  core/  →  utils/
Импорты только пакетные: from crypto_ai_bot.utils.logging import get_logger

ENV читаем только в core/settings.py

Денежные величины — Decimal

Брокеры: PaperBroker (симулятор), CcxtBroker/LiveBroker (live/sandbox)

Нет core/brokers/live.py с прямыми вызовами биржи — всё делает Ccxt-адаптер/LiveBroker

Import-Linter контролирует слои (app/ не импортируется из core/utils и т. д.)

Единый IBroker

fetch_ticker(symbol) -> TickerDTO

fetch_balance(symbol) -> BalanceDTO(free_quote, free_base)

create_market_buy_quote(symbol, quote_amount, client_order_id)

create_market_sell_base(symbol, base_amount, client_order_id)

Gate.io / CCXT

Нормализация символов, precision/limits, квантование, rate-limit/circuit-breaker/retry

📦 Структура проекта (финальная)
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
   │  ├─ brokers/{base.py,ccxt_adapter.py,paper.py,symbols.py,live.py}
   │  ├─ risk/{manager.py,protective_exits.py}
   │  ├─ reconciliation/{orders.py,positions.py,balances.py}
   │  ├─ safety/{dead_mans_switch.py,instance_lock.py}
   │  ├─ monitoring/health_checker.py
   │  └─ storage/
   │     ├─ facade.py
   │     ├─ migrations/{runner.py,cli.py,*.sql}
   │     └─ repositories/{trades.py,positions.py,market_data.py,audit.py,idempotency.py}
   └─ utils/
      ├─ __init__.py
      ├─ time.py, ids.py, logging.py, metrics.py
      ├─ retry.py, circuit_breaker.py
      ├─ exceptions.py
      └─ http_client.py
⚠️ Политика импортов и чистота кода
Запрещено прямое использование os.getenv/os.environ — только Settings

Запрещено requests.get/post и urllib.request — только utils/http_client.py

В async-коде запрещено time.sleep — используйте asyncio.sleep

Эти правила закреплены в Ruff banned-api и проверяются CI. См. pyproject.toml.

📎 Дисклеймер
Торговля криптовалютой связана с риском. Используйте систему на свой страх и риск.

yaml
Копировать код

**Что поправил:** убрал наследие `app/e2e_smoke`, привёл команды CLI к актуальным entry-points, синхронизировал дерево каталогов и правила зависимостей с эталонной спецификацией, зафиксировал режимы и критичные ENV. :contentReference[oaicite:5]{index=5} :contentReference[oaicite:6]{index=6} :contentReference[oaicite:7]{index=7}

---

## Коротко — что ещё проверить локально

1) Установку и CLI:
```bash
pip install -e .
cab-smoke
Сервер:

bash
Копировать код
uvicorn crypto_ai_bot.app.server:app --reload
# открыть /ready, /health, /metrics
Импорты/архконтракты:

bash
Копировать код
python -m importlinter
ruff check