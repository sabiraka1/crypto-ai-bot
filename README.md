Совмещает быстрый старт, команды, прод-заметки и архитектурные инварианты. Синхронизирован со спецификацией и новой структурой PnL/шины/репозиториев. 

# crypto-ai-bot

Long-only автотрейдинг криптовалют (Gate.io через CCXT).  
Единая логика для paper и live: `evaluate → risk → execute_trade → protective_exits → reconcile → watchdog`.

---

## ⚡ Быстрый старт

### 1) Установка
```bash
python -m venv .venv
# Windows (PowerShell): .\.venv\Scripts\Activate.ps1
# Linux/macOS:          source .venv/bin/activate

pip install -U pip wheel
pip install -e .

2) Конфигурация

Скопируйте .env.example → .env и задайте переменные (режим, символ(ы), лимиты, ключи для live).
Ключи можно задавать безопасно (любой вариант): *_FILE, *_B64 или SECRETS_FILE.

3) Запуск сервера (локально)
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000


Эндпойнты:

GET /health — сводное состояние

GET /ready — готовность (200/503)

GET /metrics — Prometheus-метрики (встроенный no-op сборщик)

GET /pnl/today — FIFO-PnL за сегодня (единая точка истины)

POST /orchestrator/start|stop, GET /orchestrator/status (при API_TOKEN — Bearer)

4) CLI
# Smoke-тест сборки/запуска
cab-smoke

# Обслуживание БД
cab-maintenance backup
cab-maintenance rotate --days 30
cab-maintenance vacuum
cab-maintenance integrity
cab-maintenance list

# Сверки
cab-reconcile

# Мониторинг health по HTTP (когда сервер запущен)
cab-health --oneshot --url http://127.0.0.1:8000/health

# Отчёт по сделкам/PNL/частоте за сегодня (FIFO)
cab-perf


Альтернативно:

python -m crypto_ai_bot.cli.smoke
python -m crypto_ai_bot.cli.maintenance backup
python -m crypto_ai_bot.cli.reconcile
python -m crypto_ai_bot.cli.health_monitor --oneshot --url http://127.0.0.1:8000/health
python -m crypto_ai_bot.cli.performance

🎛️ Режимы

PAPER (MODE=paper) — симулятор с реальной логикой: идемпотентность, риски, защитные выходы, сверки.

LIVE (MODE=live) — реальные ордера через CCXT.

Gate.io не имеет отдельного spot-sandbox, поэтому рекомендуем малые лимиты/саб-аккаунт.

🔐 Безопасность и риски

Идемпотентность: bucket_ms + TTL (ключи в БД, UNIQUE на clientOrderId).

RiskManager: cooldown, лимит спреда, max position (base), max orders/hour, дневной loss-limit по quote.

ProtectiveExits: hard stop + trailing (per settings).

Live-only: Dead Man’s Switch + InstanceLock.

Управляющие ручки защищены API_TOKEN (Bearer).

Durable шина: EVENT_BUS_URL=redis://... (иначе in-memory fallback).

🔄 Сверки

Оркестратор периодически запускает:

OrdersReconciler — открытые ордера (если брокер поддерживает fetch_open_orders)

PositionsReconciler — локальная позиция vs. биржевой баланс base

BalancesReconciler — свободные base/quote

🗄️ База данных

SQLite; миграции применяются при старте (migrations/runner.py).
Резервные копии/ротация/проверка целостности — через CLI.

📊 Наблюдаемость

GET /health, GET /ready — liveness/readiness

GET /metrics — Prometheus-текст

Логи — структурные (JSON), поля корреляции

Telegram-алерты: в app/compose.py подписчик шины (trade.completed/blocked/failed, budget.exceeded, watchdog.heartbeat).
При пустых TELEGRAM_* — безопасный no-op.

⚙️ ENV (ключевые)

Режим/Биржа

MODE=paper|live
EXCHANGE=gateio
SYMBOL=BTC/USDT          # или список через запятую: SYMBOLS=BTC/USDT,ETH/USDT


Торговля/Риски

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


Ключи (любой вариант)

API_KEY=...
API_SECRET=...
# или:
API_KEY_FILE=/path/to/key
API_SECRET_FILE=/path/to/secret
# или:
API_KEY_B64=base64...
API_SECRET_B64=base64...
# или:
SECRETS_FILE=/path/to/secrets.json


Telegram (опционально)

TELEGRAM_BOT_TOKEN=...
TELEGRAM_BOT_SECRET=...
TELEGRAM_CHAT_ID=123456789


Шина/Хранилище/Сервис

EVENT_BUS_URL=redis://localhost:6379/0   # опционально; без него in-memory
DB_PATH=/data/crypto_ai_bot.db
HTTP_TIMEOUT_SEC=30
LOG_LEVEL=INFO

🧱 Архитектура и инварианты

Слои: app/ → core (application → domain → infrastructure) → utils/.
ENV читаем только в core/infrastructure/settings.py.
Денежные величины — Decimal; входы приводим через utils.decimal.dec(...).
Брокеры: PaperBroker (симулятор) и CcxtBroker (live).
Import-Linter контролирует слои и запрет «application → infrastructure».