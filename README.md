# CRYPTO-AI-BOT — фундаментальная архитектура торгового бота

Production-grade фундамент (ядро) для будущего функционала: строгие интерфейсы, событийная шина с порядком по ключу, идемпотентность, метрики/health, чистый DI и изолированные слои. Репозиторий уже покрыт тестами (**23 passed**).

---

## 🚀 Ключевые возможности

- **Чёткая семантика ордеров (без двусмысленности):**
  - `create_market_buy_quote(symbol, quote_amount)` → сумма **в котируемой валюте** (например, USDT).
  - `create_market_sell_base(symbol, base_amount)` → количество **в базовой валюте** (например, BTC).
- **Событийная шина (EventBus):**
  - Per-key ordering (строгий порядок внутри `(topic, key)`), параллелизм между ключами.
  - Ленивый старт воркеров (надёжно работает в синхронном DI/тестах).
  - DLQ с метаданными и отдельными подписчиками.
  - Ретраи на временные ошибки с экспоненциальным бэк-оффом.
- **Идемпотентность операций:** стабильные ключи с бакетизацией по времени, TTL.
- **Риск-менеджмент и защитные выходы:** cooldown, спред-фильтр, `ProtectiveExits` (TP/SL-план).
- **Сигналы:** базовые фичи (SMA/EMA/спред), политика `buy/sell/hold`.
- **Хранилище:** SQLite + миграции, фасад репозиториев (trades, positions, market_data, audit, idempotency).
- **Мониторинг:** `/health` агрегирует DB/миграции/брокер/EventBus, `/metrics` — Prometheus или JSON fallback.
- **DI и сервер:** FastAPI (`/live`, `/ready`, `/health`, `/status`, `/metrics`, `/telegram/webhook`).
- **Тесты:** unit + integration, быстрый смок-скрипт.

---

## 🧱 Структура проекта

src/crypto_ai_bot/
├─ app/
│ ├─ compose.py # DI-контейнер, lifecycle (startup/shutdown)
│ ├─ server.py # FastAPI эндпоинты
│ └─ adapters/telegram.py # парсер /eval, /buy <USDT>, /sell [BASE]
├─ core/
│ ├─ events/
│ │ └─ bus.py # AsyncEventBus: per-key order, DLQ, lazy start
│ ├─ brokers/
│ │ ├─ backtest_exchange.py
│ │ └─ ccxt_exchange.py # live-режим (например, Gate.io)
│ ├─ storage/
│ │ ├─ sqlite_adapter.py
│ │ ├─ migrations/
│ │ │ ├─ runner.py
│ │ │ └─ 0001_init.sql # чистый SQL (без markdown-фенсов)
│ │ └─ repositories/ # idempotency, trades, positions, market_data, audit
│ ├─ use_cases/ # evaluate, place_order, execute_trade, reconcile, eval_and_execute
│ ├─ risk/ # RiskManager, ProtectiveExits
│ ├─ signals/ # _build (SMA/EMA/спред), policy
│ ├─ monitoring/ # HealthChecker
│ └─ analytics/ # PnL/метрики отчёта
└─ utils/ # time, ids, logging, metrics, retry, circuit_breaker, exceptions

makefile
Копировать
Редактировать

Тесты:
tests/
├─ unit/
├─ integration/
└─ conftest.py

yaml
Копировать
Редактировать

---

## 🧩 Технологии

- Python **3.12+** (совместимо с 3.13)
- FastAPI, httpx, pydantic (в составе FastAPI), sqlite3
- (опц.) prometheus_client — текстовый `/metrics`
- ccxt — для live-бирж (в dev не обязателен)
- pytest, anyio/pytest-asyncio — тестирование

---

## ⚙️ Установка

```bash
# 1) Клонирование
git clone <your-repo-url>
cd crypto-ai-bot

# 2) Виртуальное окружение (рекомендуется)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3) Зависимости
pip install -r requirements.txt
pip install -r requirements-dev.txt
Windows с пробелами в пути — используйте кавычки:

bat
Копировать
Редактировать
cd "C:\Users\<USERNAME>\Documents\GitHub\crypto-ai-bot"
🔧 Конфигурация (ENV)
Основные переменные окружения (см. core/settings.py):

ENV	Назначение	Пример
MODE	paper | live	paper
EXCHANGE	имя биржи для live (ccxt)	gateio
SYMBOL	торговая пара	BTC/USDT
DB_PATH	путь к SQLite БД	./crypto_ai_bot.db
FIXED_AMOUNT	дефолтная сумма покупки (quote)	10
IDEMPOTENCY_BUCKET_MS	ширина бакета для ключей	60000
IDEMPOTENCY_TTL_SEC	TTL ключей идемпотентности	60
API_KEY / API_SECRET	ключи для live-режима	...
TELEGRAM_ENABLED	1 включает обработчик вебхука	0

Settings.load() — единственная точка чтения ENV; валидация — в core/validators/settings.py.

▶️ Запуск сервера
bash
Копировать
Редактировать
uvicorn crypto_ai_bot.app.server:app --reload
# Открой:
# GET /live   → {"ok": true}
# GET /ready  → 200/503 (DB & миграции)
# GET /health → агрегированный отчёт (DB/миграции/брокер/EventBus)
# GET /metrics → Prometheus-текст или JSON fallback (PnL-отчёт)
# GET /status  → краткий статус/счётчики
Telegram webhook:

Включить: TELEGRAM_ENABLED=1

POST /telegram/webhook принимает стандартный update и поддерживает команды:

/eval

/buy <USDT> (сумма в котируемой валюте)

/sell [BASE] (количество в базовой валюте; без аргумента — вся позиция)

🧪 Тесты и смок-прогон
bash
Копировать
Редактировать
pytest -q
# или по группам:
pytest -q tests/unit
pytest -q tests/integration
Смок-скрипт:

bash
Копировать
Редактировать
python -m crypto_ai_bot.app.dev_smoke
# Выполнит BUY → SELL → выведет PnL и HEALTH
pytest.ini содержит pythonpath = src, поэтому импорты пакета работают из корня репо.

🧠 EventBus — гарантии и поведение
Per-key ordering — порядок строгий внутри (topic, key).

Параллелизм — разные ключи обрабатываются независимыми воркерами.

Ленивый старт — воркеры создаются только при наличии активного event loop (устойчиво в DI/pytest).

Ретраи — временные ошибки (TransientError, ConnectionError, TimeoutError, asyncio.TimeoutError) ретраятся с экспоненциальным бэк-оффом.

DLQ — при исчерпании попыток событие уходит в DLQ; подписки через subscribe_dlq().

📊 Метрики и Health
/metrics:

Если установлен prometheus_client — отдаётся Prometheus-текст.

Иначе — JSON fallback (PnL-отчёт из core/analytics/metrics.py).

HealthChecker проверяет:

доступность БД и таблицы миграций,

fetch_ticker брокера,

loopback-публикацию EventBus (если есть шина),

clock drift (если передан замер).

📚 Миграции (SQLite)
Миграции читаются через importlib.resources из пакета core/storage/migrations.
Важно: 0001_init.sql — чистый SQL, без markdown-фенсов и # комментариев (используйте --).

Запуск миграций происходит в app/compose.py при построении контейнера.

🔒 Live-режим (ccxt)
Установите ccxt, задайте MODE=live, EXCHANGE, API_KEY, API_SECRET.

BUY — сумма в quote; SELL — количество в base.

Проверь precision/минимальные суммы конкретной биржи.

Рекомендуется безопасный dry-run на тестовой сети (если доступна).

🧰 Makefile / CI / Линтинг
Если присутствуют:

Makefile — цели make test, make run, make fmt, make lint.

GitHub Actions (.github/workflows/ci.yml) — линт/типы/тесты/coverage.

pyproject.toml — конфиги ruff, mypy, coverage.

🆘 Troubleshooting
unrecognized token: "#" при миграциях — в 0001_init.sql остались маркдаун-фенсы. Оставьте только чистый SQL и -- комментарии.

RuntimeError: no running event loop — в старых версиях шины воркеры создавались в __init__. В текущей версии EventBus — ленивый старт, проблема решена.

Windows пути с пробелами — используйте кавычки в cd "C:\Users\...".

SQLite lock — закрывайте ресурсы: await bus.close(), broker.close() (если async), conn.close().

📜 Лицензия
© Выбор лицензии за владельцем репозитория.