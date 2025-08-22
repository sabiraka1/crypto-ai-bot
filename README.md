# CRYPTO-AI-BOT — фундаментальная архитектура торгового бота

Production-grade фундамент (ядро) для будущего функционала: строгие интерфейсы, событийная шина с порядком по ключу, идемпотентность, метрики/health, чистый DI и изолированные слои. Репозиторий уже покрыт тестами (**32 passed**).

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

```
src/crypto_ai_bot/
├─ app/
│  ├─ compose.py                  # DI-контейнер, lifecycle (startup/shutdown)
│  ├─ server.py                   # FastAPI эндпоинты
│  └─ adapters/telegram.py        # парсер /eval, /buy <USDT>, /sell [BASE]
├─ core/
│  ├─ events/
│  │  └─ bus.py                   # AsyncEventBus: per-key order, DLQ, lazy start
│  ├─ brokers/
│  │  ├─ backtest_exchange.py
│  │  └─ ccxt_exchange.py         # live-режим (например, Gate.io)
│  ├─ storage/
│  │  ├─ sqlite_adapter.py
│  │  ├─ migrations/
│  │  │  ├─ runner.py
│  │  │  └─ 0001_init.sql         # чистый SQL (без markdown-фенсов)
│  │  └─ repositories/            # idempotency, trades, positions, market_data, audit
│  ├─ use_cases/                  # evaluate, place_order, execute_trade, reconcile, eval_and_execute
│  ├─ risk/                       # RiskManager, ProtectiveExits
│  ├─ signals/                    # _build (SMA/EMA/спред), policy
│  ├─ monitoring/                 # HealthChecker
│  └─ analytics/                  # PnL/метрики отчёта
└─ utils/                         # time, ids, logging, metrics, retry, circuit_breaker, exceptions
```

```
Тесты:
tests/
├─ unit/
├─ integration/
└─ conftest.py
```

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
```

Windows с пробелами в пути — используйте кавычки:

```bat
cd "C:\Users\<USERNAME>\Documents\GitHub\crypto-ai-bot"
```

## 🔧 Конфигурация (ENV)

Основные переменные окружения (см. `core/settings.py`):

| ENV | Назначение | Пример |
|-----|------------|--------|
| MODE | paper \| live | paper |
| EXCHANGE | имя биржи для live (ccxt) | gateio |
| SYMBOL | торговая пара | BTC/USDT |
| DB_PATH | путь к SQLite БД | ./crypto_ai_bot.db |
| FIXED_AMOUNT | дефолтная сумма покупки (quote) | 10 |
| IDEMPOTENCY_BUCKET_MS | ширина бакета для ключей | 60000 |
| IDEMPOTENCY_TTL_SEC | TTL ключей идемпотентности | 60 |
| API_KEY / API_SECRET | ключи для live-режима | ... |
| TELEGRAM_ENABLED | 1 включает обработчик вебхука | 0 |

`Settings.load()` — единственная точка чтения ENV; валидация — в `core/validators/settings.py`.

## ▶️ Запуск сервера

```bash
uvicorn crypto_ai_bot.app.server:app --reload
# Открой:
# GET /live   → {"ok": true}
# GET /ready  → 200/503 (DB & миграции)
# GET /health → агрегированный отчёт (DB/миграции/брокер/EventBus)
# GET /metrics → Prometheus-текст или JSON fallback (PnL-отчёт)
# GET /status  → краткий статус/счётчики
```

Telegram webhook:

- Включить: `TELEGRAM_ENABLED=1`
- `POST /telegram/webhook` принимает стандартный update и поддерживает команды:
  - `/eval`
  - `/buy <USDT>` (сумма в котируемой валюте)
  - `/sell [BASE]` (количество в базовой валюте; без аргумента — вся позиция)

## 🧪 Тесты и смок-прогон

```bash
pytest -q
# или по группам:
pytest -q tests/unit
pytest -q tests/integration
```

Смок-скрипт:

```bash
python -m crypto_ai_bot.app.dev_smoke
# Выполнит BUY → SELL → выведет PnL и HEALTH
```

`pytest.ini` содержит `pythonpath = src`, поэтому импорты пакета работают из корня репо.

## 🧠 EventBus — гарантии и поведение

- **Per-key ordering** — порядок строгий внутри `(topic, key)`.
- **Параллелизм** — разные ключи обрабатываются независимыми воркерами.
- **Ленивый старт** — воркеры создаются только при наличии активного event loop (устойчиво в DI/pytest).
- **Ретраи** — временные ошибки (TransientError, ConnectionError, TimeoutError, asyncio.TimeoutError) ретраятся с экспоненциальным бэк-оффом.
- **DLQ** — при исчерпании попыток событие уходит в DLQ; подписки через `subscribe_dlq()`.

## 📊 Метрики и Health

**/metrics:**

- Если установлен `prometheus_client` — отдаётся Prometheus-текст.
- Иначе — JSON fallback (PnL-отчёт из `core/analytics/metrics.py`).

**HealthChecker** проверяет:

- доступность БД и таблицы миграций,
- `fetch_ticker` брокера,
- loopback-публикацию EventBus (если есть шина),
- clock drift (если передан замер).

## 📚 Миграции (SQLite)

- Миграции читаются через `importlib.resources` из пакета `core/storage/migrations`.
- **Важно:** `0001_init.sql` — чистый SQL, без markdown-фенсов и `#` комментариев (используйте `--`).
- Запуск миграций происходит в `app/compose.py` при построении контейнера.

## 🔒 Live-режим (ccxt)

- Установите `ccxt`, задайте `MODE=live`, `EXCHANGE`, `API_KEY`, `API_SECRET`.
- **BUY** — сумма в quote; **SELL** — количество в base.
- Проверь precision/минимальные суммы конкретной биржи.
- Рекомендуется безопасный dry-run на тестовой сети (если доступна).

## 🧰 Makefile / CI / Линтинг

Если присутствуют:

- **Makefile** — цели `make test`, `make run`, `make fmt`, `make lint`.
- **GitHub Actions** (`.github/workflows/ci.yml`) — линт/типы/тесты/coverage.
- **pyproject.toml** — конфиги ruff, mypy, coverage.

## 🆘 Troubleshooting

- `unrecognized token: "#"` при миграциях — в `0001_init.sql` остались маркдаун-фенсы. Оставьте только чистый SQL и `--` комментарии.
- `RuntimeError: no running event loop` — в старых версиях шины воркеры создавались в `__init__`. В текущей версии EventBus — ленивый старт, проблема решена.
- Windows пути с пробелами — используйте кавычки в `cd "C:\Users\..."`.
- SQLite lock — закрывайте ресурсы: `await bus.close()`, `broker.close()` (если async), `conn.close()`.

---

## Архитектура слоёв

```
src/crypto_ai_bot
├─ utils/                         # время, id, логирование, retry, circuit breaker, метрики
├─ core/
│  ├─ events/                     # AsyncEventBus (per-key order, DLQ)
│  ├─ brokers/                    # протокол IBroker + DTO, ccxt_exchange (live), symbols
│  ├─ storage/                    # facade + repositories (sqlite), migrations
│  ├─ risk/                       # RiskManager, ProtectiveExits
│  ├─ validators/                 # валидация DTO/настроек
│  ├─ monitoring/                 # HealthChecker
│  ├─ use_cases/                  # place_order, eval_and_execute (бизнес-циклы)
│  ├─ orchestrator.py             # оркестратор циклов (eval/exits/reconcile/watchdog)
│  └─ analytics/metrics.py        # JSON-снимок метрик (фолбэк)
└─ app/
   ├─ compose.py                  # DI-контейнер, сборка компонентов
   └─ server.py                   # FastAPI endpoints (/health, /ready, /metrics, /orchestrator)
```

**Границы импортов:**  
- `app → (core, utils)`  
- `core → utils`  
- `utils → ∅`  
Проверяются import-linter'ом.

---

## Ключевые решения

### 1) Семантика ордеров — однозначно
- **BUY по QUOTE:** `create_market_buy_quote("BTC/USDT", 100.0)` — на 100 USDT.  
- **SELL по BASE:** `create_market_sell_base("BTC/USDT", 0.001)` — 0.001 BTC.  
Это исключает двусмысленность `amount`.

### 2) Идемпотентность ордеров
- Ключ: `f"{base-quote-lower}:{side}:{bucket_ms}"`, напр., `btc-usdt:buy:1755784320000`.  
- Параметры из настроек:  
  - `IDEMPOTENCY_BUCKET_MS` — окно бакета (ms)  
  - `IDEMPOTENCY_TTL_SEC` — TTL ключа (sec)
- Поведение: повторный `BUY` в том же бакете → **duplicate=true**, ордер не дублируется.

### 3) События
- `AsyncEventBus`: per-key ordering, несколько обработчиков на топик, DLQ, retry на временных ошибках.  
- Метрики: `events_published`, `events_processed{status=ok|dlq}`.

### 4) Риск-гардрейлы
- Базовые: `cooldown_sec`, `max_spread_pct`.  
- Доп.: `daily_loss_limit_quote`, `max_position_base`, `max_orders_per_hour` (по умолчанию **выключены**, не ломают поведение).  
- Метрика: `risk_blocked_total{reason=...}`.

### 5) Метрики
- Лёгкий in-memory реестр (`utils.metrics`) + фолбэк `/metrics`:
  - если есть данные — Prometheus-подобный текст,
  - иначе — JSON-снимок (`core.analytics.metrics.report_dict()`).
- Таймеры: `timer("event_handle_ms", {"topic": t})` и т.п.

---

## Настройки (ENV)

| Переменная                  | Тип     | Дефолт     | Описание |
|----------------------------|---------|------------|----------|
| `MODE`                     | str     | `paper`    | `paper` \| `live` |
| `EXCHANGE`                 | str     | `gateio`   | имя биржи в ccxt |
| `SYMBOL`                   | str     | `BTC/USDT` | торгуемая пара |
| `API_KEY`, `API_SECRET`    | str     | пусто      | обязательны в `live` |
| `FIXED_AMOUNT`             | Decimal | `10`       | фиксированная сумма **в quote** для buy |
| `IDEMPOTENCY_BUCKET_MS`    | int     | `60000`    | окно бакета идемпотентности |
| `IDEMPOTENCY_TTL_SEC`      | int     | `60`       | TTL ключей идемпотентности |
| `DB_PATH`                  | str     | `:memory:` | путь к SQLite |

> Валидация настроек: `core/validators/settings.py`. `Settings.load()` — единственная точка чтения ENV.

---

## Оркестратор

Файл: `core/orchestrator.py`.  
Циклы:
- **eval_loop** — построить фичи → решить → исполнить (use-case внутри вызывает риск/экзиты).
- **exits_loop** — поддерживает защитные выходы при открытой позиции.
- **reconcile_loop** — мягкая очистка идемпотентности/аудита (если реализованы методы).
- **watchdog_loop** — heartbeat в EventBus.

Настройка интервалов — поля `eval_interval_sec`, `exits_interval_sec`, `reconcile_interval_sec`, `watchdog_interval_sec`.  
Отладка: `force_eval_action = "buy"|"sell"|"hold"|None`.

**HTTP-ручки** (FastAPI):
- `POST /orchestrator/start`
- `POST /orchestrator/stop`
- `GET /orchestrator/status`

---

## API сервера

- `GET /health` — состояние зависимостей (health checker).
- `GET /ready` — готовность.
- `GET /metrics` — Prometheus-текст или JSON-снимок.
- `POST/GET /status` — статус контейнера/компонентов (если включено).

---

## Запуск (локально)

### 1) Установка
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt  # для разработки/тестов
```

### 2) Тесты
Windows (надёжнее вызывать через модуль):

```bat
py -m pytest -q
```

### 3) Сервер
```bash
uvicorn crypto_ai_bot.app.server:app --reload
# или python -m uvicorn crypto_ai_bot.app.server:app --reload
```

### 4) Переменные окружения (пример, PowerShell)
```powershell
$env:MODE="paper"
$env:EXCHANGE="gateio"
$env:SYMBOL="BTC/USDT"
$env:FIXED_AMOUNT="10"
$env:IDEMPOTENCY_BUCKET_MS="60000"
$env:IDEMPOTENCY_TTL_SEC="60"
```

## Качество и гарантии

- Типы/DTO жёстко зафиксированы (`brokers/base.py`).
- Семантика ордеров однозначна.
- События с гарантией порядка per-key + DLQ.
- Идемпотентность ордеров и ключей.
- Метрики везде, JSON-фолбэк для `/metrics`.
- Импорт-границы проверяются (import-linter).
- Юнит/интеграционные тесты — зелёные на Python 3.13/Windows.

## Что уже сделано / чем пользоваться

- `utils/` — готовые: time, ids, logging, metrics, retry, circuit_breaker, exceptions.
- `core/events` — готово: шина событий, темы.
- `core/brokers` — протокол + ccxt-реализация (live), парсер символов.
- `core/storage` — репозитории, facade, миграции.
- `core/risk` — RiskManager + ProtectiveExits; гардрейлы; метрика risk_blocked_total.
- `core/use_cases` — place_order / eval_and_execute.
- `core/orchestrator.py` — оркестратор; server-ручки для start/stop/status.
- `app/compose.py` — сборка DI-контейнера (режимы paper/live).
- `app/server.py` — endpoints: /health, /ready, /metrics, /orchestrator/*.

---

## 📜 Лицензия
© Выбор лицензии за владельцем репозитория.