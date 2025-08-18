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

crypto-ai-bot/
├─ src/
│ └─ crypto_ai_bot/
│ ├─ app/
│ │ ├─ init.py
│ │ ├─ server.py # FastAPI: /health, /metrics, /telegram, /status/extended, /context
│ │ └─ adapters/
│ │ ├─ init.py
│ │ └─ telegram.py # async handle_update(...)
│ │
│ ├─ core/
│ │ ├─ init.py
│ │ ├─ settings.py # единственная точка ENV
│ │ ├─ bot.py # фасад бота
│ │ ├─ orchestrator.py # планировщик, maintenance
│ │ ├─ types/
│ │ ├─ use_cases/
│ │ ├─ indicators/
│ │ ├─ signals/
│ │ ├─ risk/
│ │ ├─ positions/
│ │ ├─ brokers/
│ │ ├─ storage/
│ │ ├─ validators/
│ │ └─ events/
│ │
│ ├─ utils/
│ ├─ io/
│ └─ market_context/
│
├─ analysis/
├─ notebooks/
├─ tests/
│ ├─ unit/
│ ├─ integration/
│ ├─ contract/
│ └─ regression/
├─ scripts/
│ └─ check_architecture.sh
├─ .env.example
├─ pyproject.toml
├─ requirements.txt
├─ Procfile
├─ Dockerfile
├─ docker-compose.yml
├─ .gitignore
└─ README.md

yaml
Копировать
Редактировать

Примечание: рабочие каталоги data, charts, logs, models создаются на старте и по умолчанию монтируются в Railway Volume.

---

## Архитектурные правила

* ENV читаем только в core/settings.py
* HTTP наружу — через utils/http_client.py (никаких requests.*)
* Индикаторы — централизовано в core/indicators/unified.py
* Единственное место принятия решений — core/signals/policy.decide(...)
* Деньги: Decimal; время: UTC-aware datetime
* Структурные логи (JSON) и correlation-id; метрики через utils/metrics
* Брокер — фабрика core/brokers/base.create_broker(cfg)
* БД — через интерфейсы core/storage/interfaces.py и репозитории, транзакции атомарны
* Idempotency — все критические операции
* Нормализация символов и таймфреймов — core/brokers/symbols.py
* Запреты импортов и scripts/check_architecture.sh — часть CI

---

## FastAPI: публичные маршруты

* `GET /health` — матрица статусов (db, broker, bus, time_sync) и статус healthy|degraded|unhealthy
* `GET /metrics` — Prometheus-метрики
* `POST /telegram` — webhook Telegram  
  * заголовок `X-Telegram-Bot-Api-Secret-Token` (проверка)  
  * опционально IP allowlist

### Новые маршруты

* `GET /status/extended` — p95/p99 латентностей по ключевым операциям (decision / order / flow) с сопоставлением бюджетам p99 (в мс), текущее количество открытых позиций, snapshot контекста рынка.
* `GET /context` — «Market Context» снапшот: BTC dominance (%), Fear & Greed Index (значение + класс), DXY (если включён). Все вызовы безопасны: circuit breaker + TTL-кэш, при ошибках возвращаются `null`, основной поток не деградирует.

Пример ответа `/health`:

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

yaml
Копировать
Редактировать

### Telegram-адаптер (app/adapters/telegram.py)

Команды: /start, /status, /eval, /buy или /sell {size}, /why.

* Входные symbol и timeframe нормализуются через brokers/symbols.py
* Метрики: `tg_command_total{cmd}`

---

## Use-cases и идемпотентность

* `use_cases.evaluate(...)` — rate limit 60 в минуту, Decision с полным explain
* `use_cases.place_order(...)` — rate limit 10 в минуту, idempotency key  
  * формат ключа: `symbol:side:size:timestamp_minute:decision_id_8`  
  * `repos.idempotency.check_and_store(key, ttl=24h)` возвращает duplicate без второго ордера
* `use_cases.eval_and_execute(...)` — end-to-end flow с единым correlation-id

---

## Переменные окружения (.env.example)

> Ниже — текущий блок из примера, **оставляем как есть** для обратной совместимости:

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

markdown
Копировать
Редактировать

### Дополнительно (новые/актуальные ключи)

* **Market Context**  
CONTEXT_ENABLE=true
CONTEXT_CACHE_TTL_SEC=300
CONTEXT_HTTP_TIMEOUT_SEC=2.0
CONTEXT_BTC_DOMINANCE_URL=https://api.coingecko.com/api/v3/global
CONTEXT_FEAR_GREED_URL=https://api.alternative.me/fng/?limit=1

CONTEXT_DXY_URL= # если есть свой JSON-эндпоинт со схемой {"value": <число>}
markdown
Копировать
Редактировать

* **Performance budgets p99 (в миллисекундах):**  
PERF_BUDGET_DECISION_P99_MS=0
PERF_BUDGET_ORDER_P99_MS=0
PERF_BUDGET_FLOW_P99_MS=0

markdown
Копировать
Редактировать
`0` — выключено; при ненулевых значениях в `/metrics` выставляются флаги превышения.

* **DLQ и bus**  
BUS_DLQ_MAX=1000

yaml
Копировать
Редактировать

> Примечание: переменные `RATE_LIMIT_*` в примере выше оставлены как документационные — сам лимит задаётся в коде декоратора, а не читается из ENV.

---

## Локальный запуск

Linux/macOS (bash/zsh):

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000 --reload

shell
Копировать
Редактировать

### Быстрый старт (Windows PowerShell)

python -m venv .venv
..venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH="src"
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000 --reload

yaml
Копировать
Редактировать

После запуска должны отвечать `GET /health`, `GET /metrics`, `GET /status/extended`, `GET /context`.

---

## Запуск на Railway

1. Deploy from GitHub. Python определяется автоматически (Nixpacks).
2. Variables: перенесите значения из .env.example. Важно: `DB_PATH=/data/bot.sqlite`.
3. Volume: добавьте и примонтируйте в `/data`.
4. Start Command или Procfile:
   * Start Command: *(см. Procfile, если используете gunicorn)*
   * Публичный домен Railway: `https://SERVICE.up.railway.app`
   * Секрет в `TELEGRAM_SECRET_TOKEN`; регистрация вебхука:
     ```
     curl -X POST https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook \
       -d url=https://SERVICE.up.railway.app/telegram \
       -d secret_token=$TELEGRAM_SECRET_TOKEN
     ```
5. Проверка: `GET /health` возвращает матрицу статусов; наблюдайте Logs.

---

## Docker (опционально)

Dockerfile: базовый python slim, установка зависимостей, CMD с gunicorn и uvicorn worker. Переменная `PORT` доступна в рантайме, а не на этапе сборки.

---

## Event Bus (очередь событий)

Асинхронная шина с backpressure и DLQ. **Дефолтные стратегии (вшиты в код):**
- `DecisionEvaluated` — `keep_latest`, очередь 1024
- `OrderExecuted` — `drop_oldest`, очередь 2048
- `OrderFailed` — `drop_oldest`, очередь 2048
- `FlowFinished` — `keep_latest`, очередь 1024

Метрики:  
`bus_enqueued_total{type,strategy}`, `bus_dropped_total{type,strategy}`, `bus_delivered_total{type,handlers}`, `bus_dlq_total{type}`, `events_dead_letter_total`.

> Кастомизация стратегий через ENV будет добавлена позже; по умолчанию используются значения выше.

---

## Тесты и качество

* Unit: индикаторы, policy.decide, риск-правила, идемпотентность
* Integration: eval_and_execute с мок-брокером и реальной SQLite; переходы circuit breaker; rate limit
* Contract: соответствие интерфейсам брокеров и репозиториев
* Regression: воспроизводимый бэктест с фиксированным seed и performance budgets

Запуск: `pytest -q`

Архитектурные проверки: `scripts/check_architecture.sh` — входит в CI.

---

## Наблюдаемость и обслуживание

* `/metrics` (Prometheus): http_requests_total, telegram_updates_total, broker_latency_seconds, breaker_* (состояния circuit breaker), time_drift_ms, order_*, risk_block_total, SQLite-метрики (page_size/file_size/fragmentation и пр.).
* Оркестратор `schedule_maintenance()` выполняет VACUUM и ANALYZE по порогам.

---

## Критерии готовности

* MVP: фабрика брокеров, нормализация символов и таймфреймов, идемпотентность сквозная, /health различает healthy и degraded и unhealthy
* Production: circuit breaker, rate limiting, event bus backpressure, мониторинг time sync
* Enterprise: explainable decisions, автообслуживание БД, регрессионные тесты

---

## Изменения/фиксы (август 2025)

* `PaperExchange`/`BacktestExchange`: добавлен `from_settings(...)` для совместимости с фабрикой брокеров.
* `/status/extended`: p95/p99 по decision/order/flow + бюджеты p99 (мс) + открытые позиции + market context.
* `/context`: BTC dominance, Fear&Greed, DXY (опционально) — через circuit breaker и TTL-кэш, безопасная деградация на `null`.
* Идемпотентность: ключ формата `symbol:side:size:minute:decision_id[:8]` (выравнивание с документацией).
* `place_order`: sell-ветка использует `PositionManager.reduce(...)` (убран вызов несуществующего `reduce_or_close(...)`).
* Репозиторий трейдов: добавлены `last_closed_pnls(n)` и `get_realized_pnl(days)` (FIFO long-only) — для правил риска.
* Event Bus (async): реализованы стратегии `block | drop_oldest | keep_latest`, DLQ, метрики.
* Rate limit: единая сигнатура декоратора (`@rate_limit(max_calls=..., window=...)`), обратная совместимость со старым `limit/per`.

---

## Примечания

* Не блокируйте event-loop; тяжёлые операции выполняйте через `to_thread`.
* Внешние HTTP-запросы только через utils/http_client с санитизацией логов.
* Все каталоги имеют **init**.py; проект упакован по src-схеме.

## Appendix: Быстрый чек-лист запуска

1) Установить зависимости и выставить `PYTHONPATH`:
```bash
pip install -r requirements.txt
export PYTHONPATH=src
Скопировать .env.sample → .env, поправить SYMBOL, TIMEFRAME, при необходимости Telegram-переменные.

Запуск API:

bash
Копировать
Редактировать
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000
# health & статус
curl -s http://127.0.0.1:8000/health | jq .
curl -s http://127.0.0.1:8000/status/extended | jq .
Тестовый тик (paper mode):

bash
Копировать
Редактировать
curl -s -X POST http://127.0.0.1:8000/tick \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"BTC/USDT","timeframe":"1h","limit":200}' | jq .
Графики (SVG):

Цена: /chart/test?symbol=BTC/USDT&timeframe=1h&limit=200

Доходность: /chart/profit?symbol=BTC/USDT

Бэктест из CSV:

bash
Копировать
Редактировать
./scripts/backtest_csv.py data/btc_1h.csv \
  --symbol BTC/USDT --timeframe 1h --lookback 300 \
  --slippage-bps 2 --fee-bps 5 \
  --export-trades trades.csv --out-json bt.json --out-svg bt.svg
Метрики бэктеста попадут в /metrics через BACKTEST_METRICS_PATH.

Проверка архитектурных правил:

bash
Копировать
Редактировать
chmod +x scripts/check_architecture.sh
./scripts/check_architecture.sh
yaml
Копировать
Редактировать

---

## Что дальше предлагаю
- Пробежаться `./scripts/check_architecture.sh` — убедиться, что всё зелёное.
- Если ок: финальный мини-проход «удаление мусора» (оставшиеся пустые файлы, неиспользуемые импорты) и **маленький раздел в README по Telegram-командам** (`/help`, `/status`, `/test`, `/profit`).

Скажи, если что-то из файлов выше конфликтует — пришлю дифф для твоей версии.
::contentReference[oaicite:0]{index=0}

---

## Telegram — команды

Бот поддерживает базовые команды (ручных трейдов нет):

- `/start` — приветствие и краткая помощь.
- `/help` — список команд.
- `/status` — режим, символ, таймфрейм, кол-во открытых позиций, win-rate и DLQ шины.
- `/test [SYMBOL] [TF] [LIMIT]` — быстрый расчёт сигнала + мини-график цены (ссылка).
  - Примеры: `/test`, `/test BTC/USDT 1h 300`
- `/profit` — кривая доходности (ссылка) + текущая суммарная equity.
- `/eval [SYMBOL] [TF] [LIMIT]` — расчёт решения (action/score/score_blended).
- `/why [SYMBOL] [TF] [LIMIT]` — объяснение решения: signals, weights, thresholds, context.

> Примечание: ссылки на графики в ответах бота появляются, если задан `PUBLIC_BASE_URL`.

### Настройка вебхука
1. Установить переменные окружения в `.env`:
TELEGRAM_BOT_TOKEN=<ваш_токен>
TELEGRAM_WEBHOOK_SECRET=<необязательный_секрет>
PUBLIC_BASE_URL=https://<домен_бота>

markdown
Копировать
Редактировать
2. Настроить вебхук Telegram на `POST <PUBLIC_BASE_URL>/telegram`.  
   Если задан `TELEGRAM_WEBHOOK_SECRET`, Telegram должен слать заголовок  
   `X-Telegram-Bot-Api-Secret-Token: <ваш_секрет>`.

---

## Графики (SVG)

Сервер отдает простые SVG-графики без внешних библиотек:

- Цена:  
  `GET /chart/test?symbol=BTC/USDT&timeframe=1h&limit=200`
- Доходность (equity):  
  `GET /chart/profit`

Если задать `PUBLIC_BASE_URL`, Telegram-бот будет слать кликабельные ссылки на эти эндпоинты.

---

## Метрики и бэктест

- Общие метрики: `GET /metrics` (Prometheus text format).
- Метрики SQLite: `sqlite_file_size_bytes`, `sqlite_fragmentation_percent`, и др.
- Бюджеты p99 (ms): `PERF_BUDGET_DECISION_P99_MS`, `PERF_BUDGET_ORDER_P99_MS`, `PERF_BUDGET_FLOW_P99_MS`.

### Экспорт метрик бэктеста в /metrics
В `.env` укажите путь:
BACKTEST_METRICS_PATH=backtest_metrics.json

yaml
Копировать
Редактировать
Скрипт бэктеста пишет JSON с полями:
- `backtest_trades_total`
- `backtest_equity_last`
- `backtest_max_drawdown_pct`

Сервер подхватит файл и опубликует гейджи в `/metrics`.

---

## Быстрый старт (Makefile)

```bash
# запуск в dev-режиме (reload)
make dev

# тесты и архитектурные проверки
make test
make check-arch

# SVG-графики рядом
make chart
yaml
Копировать
Редактировать

---

Если хочешь — в самом конце могу добавить мини-раздел в README про **/config/validate** (что именно проверяет) и всё — проект будет упакован полностью.
::contentReference[oaicite:0]{index=0}