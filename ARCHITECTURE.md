ARCHITECTURE

Автотрейдинг с единой бизнес-цепочкой:
strategies → regime filter → risk/limits → execute_trade → protective_exits → reconcile → watchdog → settlement

Цели: безопасность по умолчанию, чистая архитектура (строгие границы слоёв), наблюдаемость, готовность к продакшену (Railway + Redis + Alertmanager→Telegram).

Ключевые принципы: единый путь размещения ордеров, инварианты настроек, идемпотентность, минимизация дублей, модульность.

1) Контуры системы
flowchart LR
  subgraph App
    API[HTTP API (FastAPI)]
    TGP[Telegram Publisher]
    TGB[Telegram Bot]
    SUB[Telegram Subscriber]
  end

  subgraph Core.Application
    ORCH[Orchestrator]
    UCE(exec · eval_and_execute)
    SETT(settlement · partial_fills)
    EXITS(ProtectiveExits)
    RECON(Reconciliation)
    HEALTH(HealthChecker)
    EVT[events_topics.py]
    GATE(GatedBroker wrapper)
  end

  subgraph Core.Domain
    RSK[RiskManager + Rules]
    SIGS[Signals/MTF/Fusion]
    MACRO[RegimeDetector]
  end

  subgraph Core.Infrastructure
    BRK[Broker (CCXT adapter)]
    BUS[EventBus (Redis/InMem)]
    STOR[Storage (SQLite + Migrations)]
    CFG[Settings + Schema]
    SAFE[DeadManSwitch/InstanceLock]
    MACSRC[Macro Sources (DXY/BTC.d/FOMC)]
  end

  App --> ORCH
  TGB --> API
  SUB --> BUS
  ORCH --> UCE
  ORCH --> EXITS
  ORCH --> RECON
  ORCH --> HEALTH
  ORCH --> SETT
  UCE --- RSK
  UCE --> BRK
  SETT --> BRK
  ORCH --> BUS
  BUS --> SUB
  SUB --> TGP
  ORCH --> STOR
  RSK --> STOR
  RECON --> BRK
  RECON --> STOR
  HEALTH --> STOR
  HEALTH --> BRK
  GATE --- BRK
  MACRO --- GATE
  CFG -. validates .- App
  CFG -. validates .- ORCH
  SAFE --- ORCH

2) Слои и правила разграницения
Слои

app/ — входные/выходные интерфейсы (HTTP API, Telegram publisher/bot), сборка зависимостей (compose.py), подписчики.

core/application/ — оркестрация, use-cases, бизнес-процессы, protective exits, settlement, reconciliation, health, реестр событий.

core/domain/ — чистые бизнес-правила (risk-rules, стратегии, сигналы, режимы рынка).

core/infrastructure/ — брокеры (CCXT/Gate.io), storage (SQLite+миграции), event bus (Redis/in-mem), safety (DMS/lock), settings/schema, macro sources.

utils/ — Decimal, метрики, логи, retry/http, trace/CID, symbols, pnl, time.

Жёсткие правила (инварианты импортов)

app → может импортировать core.application, core.infrastructure, utils.

core.application → может импортировать core.domain, utils (нельзя app/core.infrastructure).

core.domain → может импортировать только utils.

core.infrastructure → может импортировать utils.

Темы событий — только из core/application/events_topics.py (никаких «магических строк»).

Контроль выполняет importlinter.ini (включён в CI).

3) Бизнес-конвейер и последовательности
Общая последовательность (run loop)
sequenceDiagram
  participant STR as Strategies/Signals
  participant REG as RegimeDetector
  participant RSK as RiskManager
  participant EXE as execute_trade
  participant BRK as Broker(CCXT)
  participant SET as Settlement
  participant REC as Reconcile
  participant WD as Watchdog
  participant BUS as EventBus
  participant ST as Storage

  STR->>RSK: Decision candidate
  REG->>EXE: GatedBroker (risk_on/off)
  RSK->>EXE: check(...) ok/blocked
  EXE->>BRK: create_market_* (idempotent)
  EXE->>ST: trades.add_from_order(order), orders.upsert_open(order)
  EXE->>BUS: trade.completed / trade.failed
  SET->>BRK: fetch_order / fill progress
  SET->>ST: orders.update_progress / mark_closed + trades.add_from_order
  SET->>BUS: trade.settled / trade.settlement_timeout
  REC->>BRK: positions/balances
  REC->>ST: reconcile*
  WD->>ST: health(db) / DMS / hints
  WD->>BUS: health.report / safety.dms.*

4) Порты и адаптеры
Application Ports (минимум)

BrokerPort: fetch_ticker, create_market_buy_quote, create_market_sell_base, fetch_order, fetch_order_by_client_id?
Адаптер: core/infrastructure/brokers/ccxt_adapter.py (+ fabric factory.py).

EventBusPort: publish, subscribe|on, start/stop?
Адаптер: AsyncEventBus (in-mem), RedisEventBus (+ bus_adapter.UnifiedEventBus).

StoragePort (через фасад): trades, orders, positions, balances, idempotency, audit.

SafetySwitchPort: DeadMansSwitch (DMS) — защищённая распродажа.

Telegram

Publisher (app/adapters/telegram.py): только исходящие, ретраи/дедуп, HTML.

Bot (app/adapters/telegram_bot.py): входящие команды, whitelist/roles, вызывает UC/орк через DI.

Subscriber (app/subscribers/telegram_alerts.py): слушает EventBus, форматирует и отправляет в Telegram; умеет сводки из Alertmanager.

5) Реестр событий (core/application/events_topics.py)
Категория	Тема
Order	order.executed, order.failed
Trade	trade.completed, trade.failed, trade.settled, trade.settlement_timeout, trade.blocked, trade.partial_followup
Risk/Budget	risk.blocked, budget.exceeded
Orchestrator	orchestrator.auto_paused, orchestrator.auto_resumed
Reconcile	reconciliation.completed, reconcile.position_mismatch
Watchdog/Health	watchdog.heartbeat, health.report
Safety	safety.dms.triggered, safety.dms.skipped
Alerts	alerts.alertmanager
Broker	broker.error

Все публикации/подписки — только через эти константы.

6) Risk Management — «одни ворота»

core/domain/risk/manager.py — единая точка check(symbol, storage) -> (ok, reason):

Правила:

LossStreakRule — серия убыточных сделок (limit/lookback).

MaxDrawdownRule — просадка (балансы + дневной PnL).

MaxOrders5mRule / MaxTurnover5mRule — анти-бёрст (5-мин лимиты).

CooldownRule — минимум времени между сделками.

DailyLossRule — дневной лимит реализованного убытка.

SpreadCapRule — лимит спрэда (через провайдер bid/ask).

CorrelationManager — анти-корреляционные группы символов.

Инварианты риска:

все лимиты — «мягкие»: 0/0.0 = выключено;

публикация событий budget.exceeded / risk.blocked через EventBus (константы тем);

метрики: risk_block_total{reason=...}, budget_exceeded_total{type=...}.

7) Regime gating (macro risk filter)

Источники: http_dxy, http_btc_dominance, http_fomc (таймауты и URL из ENV).

RegimeDetector агрегирует сигнал и даёт режим risk_on / risk_off.

В compose.py брокер заворачивается в GatedBroker при REGIME_ENABLED=1:

risk_off: блокировка новых входов (селлы разрешены опционально).

Логи и метрики по смене режима.

8) Execute & Settlement
Единый путь исполнения

use_cases/execute_trade.py — единственная точка постановки ордеров:

канонизация символа, идемпотентный client_order_id,

риск & бюджеты & spread-check (частично может жить в RiskManager),

запись trades.add_from_order(order) + orders.upsert_open(order),

публикация trade.completed|failed.

Settlement/Partial fills

use_cases/partial_fills.py:

обход orders.list_open(symbol),

fetch_order(...) → update_progress/mark_closed + best-effort trades.add_from_order,

trade.settled / trade.settlement_timeout,

partial follow-up: однократно добивает остаток (client_id с суффиксом -pf), публикует trade.partial_followup.

9) Reconcile & Watchdog

Reconcile (reconciliation/*.py): сверка позиций/балансов с биржей, события reconcile.position_mismatch и метрики.

Watchdog / Health: проверка БД/шины/брокера, DMS-интеграция, публикация health.report (Telegram оповещает только при деградации).

10) Хранилище данных

SQLite (WAL, индексы, миграции):

Таблицы: trades, orders (open/partial/closed), positions, balances, idempotency, audit.

Индексы: по символу, времени, client_order_id/broker_order_id (дедуп).

Миграции в core/infrastructure/storage/migrations/:

V0001__init.sql, индексы V0006, V0007, V0008, V0009, V0010, V0012__orders_table.sql.

Бэкапы/ротация/вакуум — scripts/ + backup.py.

11) Наблюдаемость и алёрты

Prometheus: /metrics (latency гистограммы циклов, счётчики шагов/ошибок/блокировок, бизнес-метрики).

Alertmanager → Telegram: alerts.alertmanager (подписчик агрегирует и шлёт сводку; деды/антишторм в publisher).

Telegram бот: /status, /today, /pnl, /pause, /resume, /stop, /health, /limits.

Health/Ready: /health (подробно), /ready (сжатый индикатор готовности).

12) Конфигурация и инварианты
Источник правды — core/infrastructure/settings.py

Чтение env + *_FILE + *_B64 + SECRETS_FILE.

Все значения проходят validate_settings(...) из settings_schema.py.

Обязательные инварианты (валидация на старте)

MTF: 0.40 + 0.25 + 0.20 + 0.10 + 0.05 = 1.0.

Fusion: 0.65 + 0.35 = 1.0.

Risk пределы безопасны: спред ≤ 5%, RISK_MAX_SLIPPAGE_PCT ≤ 5%, неотрицательные бюджеты/интервалы.

Broker throttle: RPS > 0, BURST > 0.

13) Безопасность

Идемпотентность: ключ на основе канонического символа/стороны/сумм/SESSION_RUN_ID, TTL в репозитории.

DMS / InstanceLock: защита от зависаний; безопасная распродажа.

Secrets: только *_FILE/*_B64/SECRETS_FILE; без прокидывания в логи.

Telegram:

Publisher — только исходящие, с антиштормом и дедупом.

Bot — whitelist/roles (ADMINS, OPERATORS), мелкие таймауты, rate-limit.

HTTP API: Bearer API_TOKEN на управлении оркестратором; CORS по минимуму.

Graceful shutdown: ловим SIGTERM/SIGINT; закрываем оркестраторы (cancel tasks), EventBus (stop), брокер (CCXT session), БД.

14) Параллелизм и отказоустойчивость

Асинхронность: только asyncio.sleep, без time.sleep.

Повторы: publish обёрнут retry + гистограммы; брокерные вызовы при необходимости — retry на уровне адаптера.

DLQ/логика ошибок: ошибочные шаги увеличивают метрики и публикуют события; критические — сигнализируются в Telegram.

15) Тестовая стратегия

Пирамида:

Unit: risk-rules, execute_trade, settlement, reconciliation helpers, settings validation.

Integration: paper trades через CCXT/mock, RedisEventBus, SQLite migrations.

E2E (smoke): cab-smoke, cab-health-monitor, cab-perf на sandbox конфиге.

CI:

mypy, ruff/flake8, pytest -q, import-linter — на PR и main.

Публикация артефактов (coverage, mypy report).

16) Продакшен и деплой

Railway:

Процессы: web (uvicorn FastAPI), worker (health-monitor).

Переменные окружения: Broker creds, Redis URL, Telegram, Risk caps.

База: SQLite (WAL) на диске Railway; включить регулярный бэкап/ротацию.

Наблюдаемость: внешние Prometheus/Alertmanager/Grafana (конфиг — вне репозитория; в приложении только webhook обработчик).

17) Краткая памятка по папкам/файлам

app/compose.py — сборка зависимостей: Settings→Storage→Bus→Broker(±Gated)→Risk→Exits→Health→Orchestrators + Telegram.

application/use_cases/execute_trade.py — единственный путь выставления ордеров (идемпотентность, записи, события).

application/use_cases/partial_fills.py — сеттлмент: синхронизация open-orders, догон частичных, события.

application/events_topics.py — все темы EventBus.

domain/risk/manager.py — единый risk-контур (правила внутри rules/*).

infrastructure/brokers/ccxt_adapter.py — Gate.io/CCXT адаптер.

infrastructure/storage/migrations/*.sql — схема БД и индексы.

utils/decimal.py — только Decimal для денег.

utils/metrics.py — счётчики/гистограммы/обёртки.

utils/trace.py — CID-контекст для трассировки.

18) План развития (рекомендации)

Полная выносная конфигурация правил риск-профилей (preset-ы: conservative/balanced/aggressive).

Перенос spread-check полностью в RiskManager через провайдер спрэда из брокера.

Расширение signals/* (feature store, кэш свечей, резервы памяти).

Расчёт PnL: расширенные отчёты (по символам/периодам), регресс-тесты FIFO/fee_quote.

Авто-тюнинг интервалов циклов на основе метрик (adaptive loops).