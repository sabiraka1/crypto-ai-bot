# crypto-ai-bot — FastAPI ASGI trading service

Лёгкий и прозрачный крипто-бот на **FastAPI**, со слоями `app/core/utils`, единым пайплайном сигналов и понятными правилами эксплуатации. Этот README — **актуальная и практичная** версия: как устроено, как запустить, что проверить.

> Обновлено: 2025-08-18

---

## TL;DR
- **Стек:** Python 3.12+, FastAPI (ASGI)
- **Сервер:** Uvicorn (dev), Gunicorn+UvicornWorker (prod)
- **Биржа:** через `ccxt` (режимы: paper/backtest/live; пример — Gate.io)
- **Сигналы:** EMA / RSI / MACD / ATR; решение — `core/signals/policy.decide()`
- **Хранилище:** SQLite; репозитории (`trades`, `positions`, `idempotency`, `audit`)
- **Event Bus:** асинхронная шина с backpressure и DLQ; метрики *bus_*; health/snapshots
- **Наблюдаемость:** `/health`, `/metrics` (Prometheus), структурные JSON‑логи, correlation‑id
- **Telegram:** команды `/help`, `/status`, `/test`, `/profit`, `/eval`, `/why` (ручных ордеров нет)

---

## Структура репозитория (актуально)

```
crypto-ai-bot/
├─ requirements.txt
├─ .env.example
├─ scripts/
│  ├─ backtest_cli.py
│  ├─ smoke_paper.sh
│  └─ check_architecture.sh
└─ src/
   └─ crypto_ai_bot/
      ├─ app/
      │  ├─ server.py          # FastAPI: /health, /metrics, /telegram, /status/extended, /chart/*, /context
      │  ├─ middleware.py      # Request/Correlation IDs, HTTP-метрики
      │  ├─ bus_wiring.py      # Сборка AsyncEventBus, журнал, квантиль-снапшоты
      │  └─ adapters/
      │     └─ telegram.py     # Команды: /help /status /test /profit /eval /why
      ├─ core/
      │  ├─ settings.py        # Единая точка чтения ENV
      │  ├─ orchestrator.py    # Планировщики/обслуживание (VACUUM/ANALYZE)
      │  ├─ use_cases/         # evaluate / eval_and_execute / place_order
      │  ├─ signals/           # _build / _fusion / policy.decide
      │  ├─ indicators/        # unified.py (индикаторы)
      │  ├─ brokers/           # интерфейсы, ccxt-реализация, symbols
      │  ├─ events/            # AsyncEventBus, протокол/инициализация
      │  ├─ risk/              # rules/manager
      │  └─ storage/           # sqlite_adapter, repositories/*
      ├─ market_context/       # snapshot и др. источники контекста
      └─ utils/                # metrics, logging, http_client, rate_limit, circuit_breaker, time_sync
```
> Синхронизировано с контрольной картой (ALL‑in‑ONE).

---

## Переменные окружения

### Минимум для старта
```env
MODE=paper
SYMBOL=BTC/USDT
TIMEFRAME=15m
POSITION_SIZE=10
ENABLE_TRADING=false

DB_PATH=./data/bot.sqlite

TELEGRAM_BOT_TOKEN=<ваш токен>
TELEGRAM_WEBHOOK_SECRET=<секрет для заголовка X-Telegram-Bot-Api-Secret-Token>
PUBLIC_BASE_URL=http://127.0.0.1:8000

EXCHANGE=gateio
GATEIO_API_KEY=
GATEIO_API_SECRET=
TZ=Europe/Istanbul
```

### Расширенные ключи (наблюдаемость/перфоманс/контекст/шина)

**Market Context**
```env
CONTEXT_ENABLE=true
CONTEXT_CACHE_TTL_SEC=300
CONTEXT_HTTP_TIMEOUT_SEC=2.0
CONTEXT_BTC_DOMINANCE_URL=https://api.coingecko.com/api/v3/global
CONTEXT_FEAR_GREED_URL=https://api.alternative.me/fng/?limit=1
# Опционально (если есть свой источник):
CONTEXT_DXY_URL=
```

**Performance budgets p99 (мс)** — 0 означает «выключено»
```env
PERF_BUDGET_DECISION_P99_MS=0
PERF_BUDGET_ORDER_P99_MS=0
PERF_BUDGET_FLOW_P99_MS=0
```

**Rate limits** (логика лимитов задаётся в декораторах; ключи — для документации/экспорта)
```env
RATE_LIMIT_ORDERS_PER_MINUTE=10
RATE_LIMIT_EVALUATE_PER_MINUTE=60
RATE_LIMIT_MARKET_CONTEXT_PER_HOUR=100
```

**Event Bus / DLQ**
```env
BUS_DLQ_MAX=1000
```

**Бэктест → /metrics**
```env
BACKTEST_METRICS_PATH=backtest_metrics.json
```

**SQLite обслуживание**
```env
SQLITE_VACUUM_THRESHOLD_MB=100
SQLITE_ANALYZE_ROWS_CHANGED=1000
```

---

## HTTP‑эндпоинты (FastAPI)

- `GET /health` — матрица статусов (db, bus, broker, time_sync) → `healthy|degraded|unhealthy`
- `GET /metrics` — Prometheus text format
- `POST /telegram` — webhook Telegram (проверяет `X-Telegram-Bot-Api-Secret-Token`)
- `GET /status/extended` — p95/p99 по decision/order/flow + бюджеты p99 (мс) + открытые позиции + market context (безопасная деградация)
- `GET /context` — снапшот «Market Context» (BTC dominance, Fear & Greed, DXY*)
- `GET /chart/test`, `GET /chart/profit` — SVG-графики

\* DXY опционален и берётся из `CONTEXT_DXY_URL`, если задан.

---

## Telegram‑команды (финальный набор)

- `/help`   — краткая справка и список команд
- `/status` — режим/символ/таймфрейм, базовая статистика
- `/test [SYMBOL] [TF] [LIMIT]`   — быстрый расчёт сигнала + ссылка на график
- `/profit` — кумулятив доходности + ссылка на график
- `/eval [SYMBOL] [TF] [LIMIT]`   — единичная оценка (в safe‑mode без исполнения)
- `/why  [SYMBOL] [TF] [LIMIT]`   — объяснение решения (signals/weights/thresholds/context)

> Если задан `PUBLIC_BASE_URL`, бот добавляет кликабельные ссылки на `/chart/*`.

### Настройка вебхука
```bash
curl -X POST https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook   -d url="$PUBLIC_BASE_URL/telegram"   -d secret_token="$TELEGRAM_WEBHOOK_SECRET"
```

---

## Локальный запуск (dev)

**Linux/macOS**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000 --reload
```

**Windows PowerShell**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH="src"
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000 --reload
```

---

## Продакшн‑запуск

**Gunicorn + UvicornWorker** (Railway / Docker):
```bash
PYTHONPATH=src gunicorn -k uvicorn.workers.UvicornWorker   -b 0.0.0.0:$PORT crypto_ai_bot.app.server:app
```
Рекомендуется Volume и `DB_PATH=/data/bot.sqlite`.

### Railway (шаги)
1. Deploy from GitHub (Nixpacks auto‑detect).
2. Перенесите переменные из `.env.example`, важно: `DB_PATH=/data/bot.sqlite`.
3. Добавьте Volume и примонтируйте в `/data`.
4. Start Command или Procfile (как выше).
5. Вебхук Telegram на `{PUBLIC_BASE_URL}/telegram` (см. команду выше).

---

## Event Bus (очередь событий)

Асинхронная шина с backpressure и DLQ. Типовые стратегии по типу события:
- `DecisionEvaluated` — `keep_latest`, очередь `1024`
- `OrderExecuted` — `drop_oldest`, очередь `2048`
- `OrderFailed` — `drop_oldest`, очередь `2048`
- `FlowFinished` — `keep_latest`, очередь `1024`

Метрики:
- `bus_enqueued_total{type,strategy}`, `bus_dropped_total{type,strategy}`
- `bus_delivered_total{type,handlers}`, `bus_dlq_total{type}`, `events_dead_letter_total`

---

## Тесты и качество

- **Unit**: индикаторы, policy.decide, риск‑правила, идемпотентность  
- **Integration**: eval_and_execute с мок‑брокером и реальной SQLite; circuit breaker; rate limit  
- **Contract**: соответствие интерфейсам брокеров и репозиториев  
- **Regression**: воспроизводимый бэктест (фиксированный seed) и performance budgets

Запуск:
```bash
pytest -q
./scripts/check_architecture.sh
```

---

## Наблюдаемость и обслуживание

- `/metrics` (Prometheus): `http_requests_total`, `telegram_updates_total`, `broker_latency_seconds`, `breaker_*`, `time_drift_ms`, `order_*`, `risk_block_total`, SQLite‑метрики (`sqlite_file_size_bytes`, `sqlite_fragmentation_percent`, …)
- Оркестратор: `VACUUM/ANALYZE` по порогам (`SQLITE_VACUUM_THRESHOLD_MB`, `SQLITE_ANALYZE_ROWS_CHANGED`)

---

## Быстрый чек‑лист перед деплоем

- [ ] `/health` и `/metrics` отвечают
- [ ] ENV читаются через `core/settings.py`
- [ ] Логи содержат `request_id`/`correlation_id`
- [ ] Идемпотентность и rate‑limit активны
- [ ] Telegram вебхук защищён секретом; команды работают
- [ ] На Railway примонтирован Volume `/data`, `DB_PATH=/data/bot.sqlite`
