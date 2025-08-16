# crypto-ai-bot — FastAPI + Gunicorn (UvicornWorker) на Railway (целевое состояние v6.1)

Полноценный README под целевую архитектуру (ASGI, FastAPI), соответствующую финальной технической карте. Описывает, что лежит в корне, как устроены слои (app/core/utils/... под src/), как запускать на Railway, какие переменные окружения требуются, и критерии готовности.

---

## TL;DR

* Стек: FastAPI (ASGI)
* Сервер: Gunicorn с UvicornWorker (uvicorn.workers.UvicornWorker)
* Биржа: Gate.io через ccxt (брокеры: live, paper, backtest)
* Сигналы: единый пайплайн индикаторов (EMA, RSI, MACD, ATR, Bollinger), политика signals.policy.decide()
* ML и Explainability: rule + AI score, Decision.explain (signals, blocks, weights, thresholds, context)
* Idempotency-first: репозиторий идемпотентности и атомарные транзакции
* Риск: risk.rules и risk.manager (time drift, spread, exposure и т.д.)
* Хранилище: SQLite (WAL, vacuum и analyze по расписанию)
* Наблюдаемость: /metrics (Prometheus), структурные JSON-логи, correlation-id
* Telegram: адаптер команд, webhook POST /telegram (секретный токен и allowlist)
* Деплой: Railway (Start Command или Procfile), Volume для данных

---

## Дерево репозитория (целевое)

```
crypto-ai-bot/
├─ src/
│  └─ crypto_ai_bot/
│     ├─ app/
│     │  ├─ __init__.py
│     │  ├─ server.py               # FastAPI: /health, /metrics, /telegram
│     │  └─ adapters/
│     │     ├─ __init__.py
│     │     └─ telegram.py          # async handle_update(...)
│     │
│     ├─ core/
│     │  ├─ __init__.py
│     │  ├─ settings.py             # единственная точка ENV
│     │  ├─ bot.py                  # фасад бота
│     │  ├─ orchestrator.py         # планировщик, maintenance
│     │  ├─ types/
│     │  ├─ use_cases/
│     │  ├─ indicators/
│     │  ├─ signals/
│     │  ├─ risk/
│     │  ├─ positions/
│     │  ├─ brokers/
│     │  ├─ storage/
│     │  ├─ validators/
│     │  └─ events/
│     │
│     ├─ utils/
│     ├─ io/
│     └─ market_context/
│
├─ analysis/
├─ notebooks/
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ contract/
│  └─ regression/
├─ scripts/
│  └─ check_architecture.sh
├─ .env.example
├─ pyproject.toml
├─ requirements.txt
├─ Procfile
├─ Dockerfile
├─ docker-compose.yml
├─ .gitignore
└─ README.md
```

Примечание: рабочие каталоги data, charts, logs, models создаются на старте и по умолчанию монтируются в Railway Volume.

---

## Архитектурные правила

* ENV читаем только в core/settings.py
* HTTP наружу — через utils/http\_client.py (никаких requests.\*)
* Индикаторы — централизовано в core/indicators/unified.py
* Единственное место принятия решений — core/signals/policy.decide(...)
* Деньги: Decimal; время: UTC-aware datetime
* Структурные логи (JSON) и correlation-id; метрики через utils/metrics
* Брокер — фабрика core/brokers/base.create\_broker(cfg)
* БД — через интерфейсы core/storage/interfaces.py и репозитории, транзакции атомарны
* Idempotency — все критические операции
* Нормализация символов и таймфреймов — core/brokers/symbols.py
* Запреты импортов и scripts/check\_architecture.sh — часть CI

---

## FastAPI: публичные маршруты

* GET /health — матрица статусов (db, broker, bus, time\_sync) и статус healthy|degraded|unhealthy
* GET /metrics — Prometheus-метрики
* POST /telegram — webhook Telegram

  * заголовок X-Telegram-Bot-Api-Secret-Token (проверка)
  * опционально IP allowlist

Пример ответа /health:

```
{
  "ok": true,
  "status": "degraded",
  "components": {
    "db": {"ok": true, "latency_ms": 2.3},
    "broker": {"ok": false, "latency_ms": 1200.0, "mode": "paper"},
    "bus": {"ok": true, "queue_size": 12},
    "time_sync": {"ok": true, "drift_ms": 120}
  },
  "version": "v6.1",
  "mode": "paper",
  "degradation_level": "no_market_context"
}
```

### Telegram-адаптер (app/adapters/telegram.py)

Команды: /start, /status, /eval, /buy или /sell {size}, /why.

* Входные symbol и timeframe нормализуются через brokers/symbols.py
* Метрики: tg\_command\_total{cmd}

---

## Use-cases и идемпотентность

* use\_cases.evaluate(...) — rate limit 60 в минуту, Decision с полным explain
* use\_cases.place\_order(...) — rate limit 10 в минуту, idempotency key

  * формат ключа: symbol\:side\:size\:timestamp\_minute\:decision\_id\_8
  * repos.idempotency.check\_and\_store(key, ttl=24h) возвращает duplicate без второго ордера
* use\_cases.eval\_and\_execute(...) — end-to-end flow с единым correlation-id

---

## Переменные окружения (.env.example)

```
MODE=paper
DEGRADATION_LEVEL=full
SYMBOL=BTC/USDT
TIMEFRAME=15m
POSITION_SIZE=10
ENABLE_TRADING=true
TZ=Europe/Istanbul

MAX_DRAWDOWN_PCT=0.2
STOP_LOSS_PCT=0.03
MAX_POSITIONS=1
MAX_TIME_DRIFT_MS=1000

RATE_LIMIT_ORDERS_PER_MINUTE=10
RATE_LIMIT_EVALUATE_PER_MINUTE=60
RATE_LIMIT_MARKET_CONTEXT_PER_HOUR=100
PERF_BUDGET_DECIDE_P99=0.5
PERF_BUDGET_ORDER_P99=1.0

DB_PATH=/data/bot.sqlite
SQLITE_VACUUM_THRESHOLD_MB=100
SQLITE_ANALYZE_ROWS_CHANGED=1000

TELEGRAM_BOT_TOKEN=FILL_ME
TELEGRAM_SECRET_TOKEN=FILL_ME

EXCHANGE=gateio
GATEIO_API_KEY=FILL_ME
GATEIO_API_SECRET=FILL_ME
GATEIO_PASSWORD=

DATA_DIR=/data
CHARTS_DIR=/data/charts
MODELS_DIR=/data/models
LOGS_DIR=/data/logs
```

---

## Локальный запуск

Linux/macOS (bash/zsh):

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000 --reload
```

### Быстрый старт (Windows PowerShell)

```
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH="src"
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000 --reload
```

После запуска должны отвечать `GET /health` и `GET /metrics`. Для теста webhook отправляйте `POST /telegram`.

---

## Запуск на Railway

1. Deploy from GitHub. Python определяется автоматически (Nixpacks).
2. Variables: перенесите значения из .env.example. Важно: DB\_PATH=/data/bot.sqlite.
3. Volume: добавьте и примонтируйте в /data.
4. Start Command или Procfile:

   * Start Command:
     gunegram:
   * Публичный домен Railway: [https://SERVICE.up.railway.app](https://SERVICE.up.railway.app)
   * Секрет в TELEGRAM\_SECRET\_TOKEN; регистрация вебхука одной командой:
     curl -X POST [https://api.telegram.org/bot\$TELEGRAM\_BOT\_TOKEN/setWebhook](https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook) -d url=[https://SERVICE.up.railway.app/telegram](https://SERVICE.up.railway.app/telegram) -d secret\_token=\$TELEGRAM\_SECRET\_TOKEN
5. Проверка: GET /health возвращает матрицу статусов; наблюдайте Logs.

---

## Docker (опционально)

Dockerfile: базовый python slim, установка зависимостей, CMD с gunicorn и uvicorn worker. Переменная PORT доступна в рантайме, а не на этапе сборки.

---

## Тесты и качество

* Unit: индикаторы, policy.decide, риск-правила, идемпотентность
* Integration: eval\_and\_execute с мок-брокером и реальной SQLite; переходы circuit breaker; rate limit
* Contract: соответствие интерфейсам брокеров и репозиториев
* Regression: воспроизводимый бэктест с фиксированным seed и performance budgets

Запуск: pytest -q

Архитектурные проверки: scripts/check\_architecture.sh — входит в CI.

---

## Наблюдаемость и обслуживание

* /metrics (Prometheus): http\_requests\_total, telegram\_updates\_total, broker\_latency\_seconds, broker\_circuit\_state, time\_drift\_ms, order\_\*, risk\_block\_total, SQLite-метрики и др.
* orchestrator.schedule\_maintenance() выполняет VACUUM и ANALYZE, ## Event Bus (очередь событий)
  Поддерживаются настройки через ENV в двух форматах — JSON или строка `k=v;...`:
* `BUS_STRATEGIES` — стратегии для каналов (например: `{ "orders": "drop_new", "signals": "block" }` или `orders=drop_new;signals=block`).
* `BUS_QUEUE_SIZES` — размеры очередей (например: `{ "orders": 1000, "signals": 5000 }` или `orders=1000;signals=5000`).
* `BUS_DLQ_MAX` — максимальный размер dead-letter очереди (число).

Если канал переполнен и стратегия `drop_new`, новые события отбрасываются с метрикой и записью в DLQ; при `block` — включается backpressure.

---

## Наблюдаемость и обслуживаниеонтролирует drift.

---

## Критерии готовности

* MVP: фабрика брокеров, нормализация символов и таймфреймов, идемпотентность сквозная, /health различает healthy и degraded и unhealthy
* Production: circuit breaker, rate limiting, event bus backpressure, мониторинг time sync
* Enterprise: explainable decisions, автообслуживание БД, регрессионные тесты

---

## Примечания

* Не блокируйте event-loop; тяжёлые операции выполняйте через to\_thread.
* Внешние HTTP-запросы только через utils/http\_client с санитизацией логов.
* Все каталоги имеют **init**.py; проект упакован по src-схеме.
